import sys
import os
import matplotlib
import PIL
import six
import numpy as np
import math
import time
import paddle
import paddle.fluid as fluid
from Net import *
from Utils import *
from Reader import *
from skimage import io,transform

img_dim = 96
LEARENING_RATE = 2e-4
SHOWNUM = 12
epoch = 300
output = "./Output/"
batch_size = 100
G_DIMENSION = 72

d_program = fluid.Program()
dg_program = fluid.Program()

###定义判别器program
# program_guard()接口配合with语句将with block中的算子和变量添加指定的全局主程序（main_program)和启动程序（start_progrom)
with fluid.program_guard(d_program):
    # 输入图片大小为28*28
    img = fluid.layers.data(name='img', shape=[None,3,img_dim,img_dim], dtype='float32')
    # 标签shape=1
    label = fluid.layers.data(name='label', shape=[None,1], dtype='int64')
    d_logit = D(img)
    d_loss = loss(x=d_logit, label=label)

###定义生成器program
with fluid.program_guard(dg_program):
    noise = fluid.layers.data(name='noise', shape=[None,G_DIMENSION], dtype='float32')
    #label = np.ones(shape=[batch_size, G_DIMENSION], dtype='int64')
    # 噪声数据作为输入得到生成照片
    g_img = G(x=noise)
    g_program = dg_program.clone()
    g_program_test = dg_program.clone(for_test=True)

    # 判断生成图片为真实样本的概率
    dg_logit = D(g_img)

    # 计算生成图片被判别为真实样本的loss
    dg_loss = loss(
        x=dg_logit,
        label=fluid.layers.fill_constant_batch_size_like(input=noise, dtype='int64', shape=[-1,1], value=1)
    )

###优化函数
opt = fluid.optimizer.Adam(learning_rate=LEARENING_RATE,beta1=0.5)
opt.minimize(loss=d_loss)
parameters = [p.name for p in g_program.global_block().all_parameters()]
opt.minimize(loss=dg_loss, parameter_list=parameters)

train_reader = paddle.batch(
    paddle.reader.shuffle(
        reader=train(), buf_size=50000
    ),
    batch_size=batch_size
)
test_reader = paddle.batch(
    paddle.reader.shuffle(
        reader=test(), buf_size=10000
    ),
    batch_size=10
)
###执行器
if use_gpu:
    exe = fluid.Executor(fluid.CUDAPlace(0))
else:
    exe = fluid.Executor(fluid.CPUPlace())
start_program = fluid.default_startup_program()
exe.run(start_program)
#加载模型
#fluid.io.load_persistables(exe,'./Model/D/',d_program)
#fluid.io.load_persistables(exe,'./Model/G/',dg_program)

###训练过程
t_time = 0
losses = [[], []]
# 判别器迭代次数
NUM_TRAIN_TIME_OF_DG = 2
# 最终生成的噪声数据
const_n = np.random.uniform(
    low=0.0, high=1.0,
    size=[batch_size, G_DIMENSION]).astype('float32')
test_const_n = np.random.uniform(
    low=0.0, high=1.0,
    size=[100, G_DIMENSION]).astype('float32')
plt.figure(figsize=(10,6))
plt.ion()
now = 0
for pass_id in range(epoch):
    fluid.io.save_persistables(exe, './Model/G', dg_program)
    fluid.io.save_persistables(exe, './Model/D', d_program)
    for batch_id, data in enumerate(train_reader()):  # enumerate()函数将一个可遍历的数据对象组合成一个序列列表
        if len(data) != batch_size:
            continue

        # 生成训练过程的噪声数据
        noise_data = np.random.uniform(
            low=0.0, high=1.0,
            size=[batch_size, G_DIMENSION]).astype('float32')
        # 真实图片
        real_image = np.array(data)
        # 真实标签
        real_labels = np.ones(shape=[batch_size,1], dtype='int64')
        # real_labels = real_labels * 10
        # 虚假标签
        fake_labels = np.zeros(shape=[batch_size,1], dtype='int64')
        s_time = time.time()
        #print(np.max(noise_data))
        # 虚假图片
        generated_image = exe.run(g_program,
                                  feed={'noise': noise_data},
                                  fetch_list=[g_img])[0]


        ###训练判别器
        # D函数判断虚假图片为假的loss
        d_loss_1 = exe.run(d_program,
                           feed={
                               'img': generated_image,
                               'label': fake_labels,
                           },
                           fetch_list=[d_loss])[0][0]
        # D函数判断真实图片为真的loss
        d_loss_2 = exe.run(d_program,
                           feed={
                               'img': real_image,
                               'label': real_labels,
                           },
                           fetch_list=[d_loss])[0][0]

        d_loss_n = d_loss_1 + d_loss_2
        losses[0].append(d_loss_n)

        ###训练生成器
        for _ in six.moves.xrange(NUM_TRAIN_TIME_OF_DG):
            noise_data = np.random.uniform(  # uniform()方法从一个均匀分布[low,high)中随机采样
                low=0.0, high=1.0,
                size=[batch_size, G_DIMENSION]).astype('float32')
            dg_loss_n = exe.run(dg_program,
                                feed={'noise': noise_data},
                                fetch_list=[dg_loss])[0][0]
        losses[1].append(dg_loss_n)
        t_time += (time.time() - s_time)

        if batch_id % 500 == 0:
            if not os.path.exists(output):
                os.makedirs(output)
            # 每轮的生成结果
            generated_image = exe.run(g_program_test, feed={'noise': test_const_n}, fetch_list=[g_img])[0]
            #print(generated_image[1])
            imgs = []
            try:
                for i in range(30):
                    image = generated_image[i].transpose()
                    plt.subplot(6, 5, i + 1)
                    plt.imshow(image)
                    plt.axis('off')
                    plt.xticks([])
                    plt.yticks([])
                    plt.subplots_adjust(wspace=0.1, hspace=0.1)
                # plt.subplots_adjust(wspace=0.1,hspace=0.1)
                msg = 'Epoch ID={0} Batch ID={1} \n D-Loss={2} G-Loss={3}'.format(pass_id, batch_id, d_loss_n, dg_loss_n)
                #print(msg)
                plt.suptitle(msg,fontsize=10)
                plt.draw()
                #if batch_id % 10000 == 0:
                plt.savefig('{}/{:04d}_{:04d}.png'.format(output, pass_id + 92, batch_id),bbox_inches='tight')
                plt.pause(0.01)
                #display.clear_output(wait=True)
                #plt.pause(0.01)
            except IOError:
                print(IOError)


plt.ioff()
plt.close()
plt.figure(figsize=(15, 6))
x = np.arange(len(losses[0]))
plt.title('Loss')
plt.xlabel('Number of Batch')
plt.plot(x,np.array(losses[0]),'r-',label='D Loss')
plt.plot(x,np.array(losses[1]),'b-',label='G Loss')
plt.legend()
plt.savefig('work/Train Process')
plt.show()
