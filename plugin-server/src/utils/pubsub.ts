import { EventEmitter } from 'events'
import { Redis } from 'ioredis'

import { PluginsServerConfig } from '../types'
import { createRedis } from './db/redis'
import { parseJSON } from './json-parse'
import { logger } from './logger'
import { PromiseScheduler } from './promise-scheduler'

export class PubSub {
    private eventEmitter: EventEmitter
    private serverConfig: PluginsServerConfig
    private redisSubscriber?: Redis
    private redisPublisher?: Promise<Redis>
    private promises: PromiseScheduler

    constructor(serverConfig: PluginsServerConfig) {
        this.eventEmitter = new EventEmitter()
        this.serverConfig = serverConfig
        this.promises = new PromiseScheduler()
    }

    public async start(): Promise<void> {
        if (this.redisSubscriber) {
            throw new Error('Started PubSub cannot be started again!')
        }
        this.redisSubscriber = await createRedis(this.serverConfig, 'ingestion')

        this.redisSubscriber.on('message', (channel: string, message: string) => {
            this.eventEmitter.emit(channel, message)
        })
        logger.info('👀', 'Pub-sub started')
    }

    public async stop(): Promise<void> {
        if (!this.redisSubscriber) {
            throw new Error('Unstarted PubSub cannot be stopped!')
        }

        await this.promises.waitForAll()
        await this.redisSubscriber.unsubscribe()

        if (this.redisSubscriber) {
            this.redisSubscriber.disconnect()
        }
        this.redisSubscriber = undefined

        if (this.redisPublisher) {
            const redisPublisher = await this.redisPublisher
            if (redisPublisher) {
                redisPublisher.disconnect()
            }
            this.redisPublisher = undefined
        }

        this.eventEmitter.removeAllListeners()

        logger.info('🛑', 'Pub-sub stopped')
    }

    public async publish(channel: string, message: string): Promise<void> {
        if (!this.redisPublisher) {
            this.redisPublisher = createRedis(this.serverConfig, 'ingestion')
        }

        const redisPublisher = await this.redisPublisher
        await redisPublisher.publish(channel, message)
    }

    public on<T extends Record<string, any>>(channel: string, listener: (message: T) => void): void {
        if (!this.redisSubscriber) {
            throw new Error('PubSub must be started before subscribing to channels!')
        }

        void this.promises.schedule(this.redisSubscriber.subscribe(channel))
        this.eventEmitter.on(channel, (message) => listener(message ? parseJSON(message) : {}))
    }
}
