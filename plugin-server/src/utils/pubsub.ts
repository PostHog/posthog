import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'

import { PluginsServerConfig } from '../types'
import { status } from './status'
import { createRedis } from './utils'

export type PubSubTask = ((message: string) => void) | ((message: string) => Promise<void>)

export interface PubSubTaskMap {
    [channel: string]: PubSubTask
}

export class PubSub {
    private serverConfig: PluginsServerConfig
    private redisSubscriber?: Redis
    private redisPublisher?: Promise<Redis>
    public taskMap: PubSubTaskMap

    constructor(serverConfig: PluginsServerConfig, taskMap: PubSubTaskMap = {}) {
        this.serverConfig = serverConfig
        this.taskMap = taskMap
    }

    public async start(): Promise<void> {
        if (this.redisSubscriber) {
            throw new Error('Started PubSub cannot be started again!')
        }
        this.redisSubscriber = await createRedis(this.serverConfig)
        const channels = Object.keys(this.taskMap)
        await this.redisSubscriber.subscribe(channels)
        this.redisSubscriber.on('message', (channel: string, message: string) => {
            const task: PubSubTask | undefined = this.taskMap[channel]
            if (!task) {
                captureException(
                    new Error(
                        `Received a pubsub message for unassociated channel ${channel}! Associated channels are: ${Object.keys(
                            this.taskMap
                        ).join(', ')}`
                    )
                )
            }
            void task(message)
        })
        status.info('👀', `Pub-sub started for channels: ${channels.join(', ')}`)
    }

    public async stop(): Promise<void> {
        if (!this.redisSubscriber) {
            throw new Error('Unstarted PubSub cannot be stopped!')
        }

        await this.redisSubscriber.unsubscribe()
        this.redisSubscriber.disconnect()
        this.redisSubscriber = undefined

        if (this.redisPublisher) {
            const redisPublisher = await this.redisPublisher
            redisPublisher.disconnect()
            this.redisPublisher = undefined
        }

        status.info('🛑', `Pub-sub stopped for channels: ${Object.keys(this.taskMap).join(', ')}`)
    }

    public async publish(channel: string, message: string): Promise<void> {
        if (!this.redisPublisher) {
            this.redisPublisher = createRedis(this.serverConfig)
        }

        const redisPublisher = await this.redisPublisher
        await redisPublisher.publish(channel, message)
    }
}
