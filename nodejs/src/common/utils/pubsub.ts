import { EventEmitter } from 'events'
import { Redis } from 'ioredis'

import { RedisPool } from '~/types'

import { parseJSON } from './json-parse'
import { logger, serializeError } from './logger'
import { PromiseScheduler } from './promise-scheduler'

export class PubSub {
    private eventEmitter: EventEmitter
    private redisSubscriber?: Redis
    private redisPublisher?: Redis
    private promises: PromiseScheduler

    constructor(private redisPool: RedisPool) {
        this.eventEmitter = new EventEmitter()
        this.promises = new PromiseScheduler()
    }

    public async start(): Promise<void> {
        if (this.redisSubscriber) {
            throw new Error('Started PubSub cannot be started again!')
        }
        this.redisSubscriber = await this.redisPool.acquire()

        this.redisSubscriber.on('message', (channel: string, message: string) => {
            this.eventEmitter.emit(channel, message)
        })
        logger.info('👀', 'Pub-sub started')
    }

    public async stop(): Promise<void> {
        if (!this.redisSubscriber) {
            logger.error('🛑', 'Unstarted PubSub cannot be stopped!')
            return
        }

        await this.promises.waitForAll()

        // Redis teardown can fail transiently during shutdown (e.g. `write ETIMEDOUT` when the
        // socket is slow or unreachable). The process is going down anyway, so tolerate it:
        // log and swallow rather than letting an unhandled rejection reach error tracking.
        try {
            await this.redisSubscriber.unsubscribe()
        } catch (error) {
            logger.warn('🛑', 'Failed to unsubscribe Redis subscriber during PubSub shutdown', {
                error: serializeError(error),
            })
        }

        if (this.redisSubscriber) {
            this.redisSubscriber.removeAllListeners('message')
            try {
                await this.redisPool.release(this.redisSubscriber)
            } catch (error) {
                logger.warn('🛑', 'Failed to release Redis subscriber during PubSub shutdown', {
                    error: serializeError(error),
                })
            }
        }
        this.redisSubscriber = undefined

        if (this.redisPublisher) {
            try {
                await this.redisPool.release(this.redisPublisher)
            } catch (error) {
                logger.warn('🛑', 'Failed to release Redis publisher during PubSub shutdown', {
                    error: serializeError(error),
                })
            }
            this.redisPublisher = undefined
        }

        this.eventEmitter.removeAllListeners()

        logger.info('🛑', 'Pub-sub stopped')
    }

    public async publish(channel: string, message: string): Promise<void> {
        if (!this.redisPublisher) {
            this.redisPublisher = await this.redisPool.acquire()
        }

        await this.redisPublisher.publish(channel, message)
    }

    public on<T extends Record<string, any>>(channel: string, listener: (message: T) => void): void {
        if (!this.redisSubscriber) {
            throw new Error('PubSub must be started before subscribing to channels!')
        }

        void this.promises.schedule(this.redisSubscriber.subscribe(channel))
        this.eventEmitter.on(channel, (message) => listener(message ? parseJSON(message) : {}))
    }
}
