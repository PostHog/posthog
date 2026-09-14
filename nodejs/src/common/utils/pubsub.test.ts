import { Redis } from 'ioredis'

import { RedisPool } from '~/types'

import { logger } from './logger'
import { PubSub } from './pubsub'

jest.mock('./logger')

describe('PubSub', () => {
    let redisPool: RedisPool
    let connections: Redis[]

    beforeEach(() => {
        jest.clearAllMocks()
        connections = []
        redisPool = {
            acquire: jest.fn(() => {
                const connection = {
                    on: jest.fn(),
                    publish: jest.fn(),
                    subscribe: jest.fn(),
                    unsubscribe: jest.fn(),
                    removeAllListeners: jest.fn(),
                } as unknown as Redis
                connections.push(connection)
                return Promise.resolve(connection)
            }),
            release: jest.fn(() => Promise.resolve()),
        } as unknown as RedisPool
    })

    it('releases the publisher when the pub-sub was never started', async () => {
        const pubSub = new PubSub(redisPool)

        await pubSub.publish('channel', 'message')
        await pubSub.stop()

        expect(redisPool.release).toHaveBeenCalledWith(connections[0])
        expect(logger.error).not.toHaveBeenCalled()
    })

    it('releases both connections when the pub-sub was started', async () => {
        const pubSub = new PubSub(redisPool)

        await pubSub.start()
        await pubSub.publish('channel', 'message')
        await pubSub.stop()

        expect(redisPool.release).toHaveBeenCalledWith(connections[0])
        expect(redisPool.release).toHaveBeenCalledWith(connections[1])
    })
})
