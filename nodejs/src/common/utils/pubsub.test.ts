import { Redis } from 'ioredis'

import { RedisPool } from '~/types'

import { PubSub } from './pubsub'

describe('PubSub', () => {
    let subscriber: jest.Mocked<Pick<Redis, 'on' | 'unsubscribe' | 'removeAllListeners' | 'subscribe'>>
    let redisPool: jest.Mocked<Pick<RedisPool, 'acquire' | 'release'>>
    let pubSub: PubSub

    beforeEach(async () => {
        subscriber = {
            on: jest.fn(),
            unsubscribe: jest.fn().mockResolvedValue(undefined),
            removeAllListeners: jest.fn(),
            subscribe: jest.fn().mockResolvedValue(undefined),
        }
        redisPool = {
            acquire: jest.fn().mockResolvedValue(subscriber),
            release: jest.fn().mockResolvedValue(undefined),
        }
        pubSub = new PubSub(redisPool as unknown as RedisPool)
        await pubSub.start()
    })

    it('swallows a transient Redis error while unsubscribing during shutdown', async () => {
        subscriber.unsubscribe.mockRejectedValue(new Error('write ETIMEDOUT'))

        await expect(pubSub.stop()).resolves.toBeUndefined()
        // still releases the subscriber back to the pool despite the unsubscribe failure
        expect(redisPool.release).toHaveBeenCalledWith(subscriber)
    })

    it('swallows a transient Redis error while releasing the subscriber during shutdown', async () => {
        redisPool.release.mockRejectedValue(new Error('write ETIMEDOUT'))

        await expect(pubSub.stop()).resolves.toBeUndefined()
    })
})
