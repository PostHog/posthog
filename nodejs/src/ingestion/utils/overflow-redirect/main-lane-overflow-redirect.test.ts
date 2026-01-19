import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { MainLaneOverflowRedirect, MainLaneOverflowRedirectConfig } from './main-lane-overflow-redirect'
import { OverflowEventBatch } from './overflow-redirect-service'

const createMockRedisPool = (mockRedis: Partial<Redis>): GenericPool<Redis> => {
    return {
        acquire: jest.fn().mockResolvedValue(mockRedis as Redis),
        release: jest.fn().mockResolvedValue(undefined),
    } as unknown as GenericPool<Redis>
}

const createBatch = (
    token: string,
    distinctId: string,
    eventCount: number = 1,
    firstTimestamp: number = Date.now()
): OverflowEventBatch => ({
    key: { token, distinctId },
    eventCount,
    firstTimestamp,
})

describe('MainLaneOverflowRedirect', () => {
    let mockRedis: jest.Mocked<Partial<Redis>>
    let mockPool: GenericPool<Redis>
    let service: MainLaneOverflowRedirect

    const defaultConfig: MainLaneOverflowRedirectConfig = {
        redisPool: null as unknown as GenericPool<Redis>,
        redisTTLSeconds: 300,
        localCacheTTLSeconds: 60,
        bucketCapacity: 10,
        replenishRate: 1,
        statefulEnabled: true,
    }

    beforeEach(() => {
        const mockPipeline = {
            set: jest.fn().mockReturnThis(),
            exec: jest.fn().mockResolvedValue([]),
        }
        mockRedis = {
            mget: jest.fn().mockResolvedValue([null]), // Default: key not in Redis
            pipeline: jest.fn().mockReturnValue(mockPipeline),
            ping: jest.fn().mockResolvedValue('PONG'),
        }
        mockPool = createMockRedisPool(mockRedis)
        service = new MainLaneOverflowRedirect({
            ...defaultConfig,
            redisPool: mockPool,
        })
    })

    describe('handleEventBatch', () => {
        it('returns empty set when no events exceed rate limit', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null])

            const batch = [createBatch('token1', 'user1', 5)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })

        it('returns keys that exceed rate limit', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null])

            // Bucket capacity is 10, so 15 events should exceed
            const batch = [createBatch('token1', 'user1', 15)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
        })

        it('flags newly rate-limited keys in Redis', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null])
            const mockPipeline = {
                set: jest.fn().mockReturnThis(),
                exec: jest.fn().mockResolvedValue([]),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            const batch = [createBatch('token1', 'user1', 15)]

            await service.handleEventBatch('events', batch)

            expect(mockPipeline.set).toHaveBeenCalledWith(
                '@posthog/stateful-overflow/events:token1:user1',
                '1',
                'EX',
                300
            )
            expect(mockPipeline.exec).toHaveBeenCalled()
        })

        it('checks Redis for keys not in local cache', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null])

            const batch = [createBatch('token1', 'user1', 5)]

            await service.handleEventBatch('events', batch)

            expect(mockRedis.mget).toHaveBeenCalledWith('@posthog/stateful-overflow/events:token1:user1')
        })

        it('returns keys that are already flagged in Redis', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue(['1'])

            const batch = [createBatch('token1', 'user1', 1)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
        })

        it('uses local cache for subsequent calls', async () => {
            // First call: Redis says key is flagged
            mockRedis.mget = jest.fn().mockResolvedValue(['1'])

            const batch1 = [createBatch('token1', 'user1', 1)]
            await service.handleEventBatch('events', batch1)

            // Reset mock
            mockRedis.mget = jest.fn().mockResolvedValue([null])

            // Second call: should use cache, not Redis
            const batch2 = [createBatch('token1', 'user1', 1)]
            const result = await service.handleEventBatch('events', batch2)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
            // mget should not have been called for the second batch
            expect(mockRedis.mget).not.toHaveBeenCalled()
        })

        it('caches negative results (not in Redis)', async () => {
            // First call: key not in Redis
            mockRedis.mget = jest.fn().mockResolvedValue([null])

            const batch1 = [createBatch('token1', 'user1', 1)]
            await service.handleEventBatch('events', batch1)

            // Reset mock
            mockRedis.mget = jest.fn().mockResolvedValue(['1'])

            // Second call: should use cache (null), not check Redis again
            const batch2 = [createBatch('token1', 'user1', 1)]
            await service.handleEventBatch('events', batch2)

            // mget should not have been called for the second batch
            expect(mockRedis.mget).not.toHaveBeenCalled()
        })

        it('handles multiple keys independently', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null, null])

            const batch = [
                createBatch('token1', 'user1', 5), // Below limit
                createBatch('token1', 'user2', 15), // Exceeds limit
            ]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user2')).toBe(true)
            expect(result.has('token1:user1')).toBe(false)
        })

        it('batches multiple Redis MGET calls', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null, null, null])

            const batch = [
                createBatch('token1', 'user1', 1),
                createBatch('token1', 'user2', 1),
                createBatch('token2', 'user1', 1),
            ]

            await service.handleEventBatch('events', batch)

            expect(mockRedis.mget).toHaveBeenCalledWith(
                '@posthog/stateful-overflow/events:token1:user1',
                '@posthog/stateful-overflow/events:token1:user2',
                '@posthog/stateful-overflow/events:token2:user1'
            )
        })
    })

    describe('fail-open behavior', () => {
        it('treats keys as not flagged when Redis MGET fails', async () => {
            mockRedis.mget = jest.fn().mockRejectedValue(new Error('Redis error'))

            const batch = [createBatch('token1', 'user1', 5)]

            const result = await service.handleEventBatch('events', batch)

            // Should not throw, and should return empty set (below rate limit)
            expect(result.size).toBe(0)
        })

        it('still redirects when Redis SET fails but rate limit exceeded', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null])
            const mockPipeline = {
                set: jest.fn().mockReturnThis(),
                exec: jest.fn().mockRejectedValue(new Error('Redis error')),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            const batch = [createBatch('token1', 'user1', 15)]

            const result = await service.handleEventBatch('events', batch)

            // Should still redirect even though Redis write failed
            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
        })
    })

    describe('rate limiting behavior', () => {
        it('rate limit state persists across batches', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null])

            // First batch: consume 8 of 10 tokens
            const batch1 = [createBatch('token1', 'user1', 8)]
            const result1 = await service.handleEventBatch('events', batch1)
            expect(result1.size).toBe(0)

            // Reset mget mock for second call (won't be called due to cache)
            mockRedis.mget = jest.fn()

            // Second batch: consume 3 more tokens (total 11, exceeds 10)
            const batch2 = [createBatch('token1', 'user1', 3)]
            const result2 = await service.handleEventBatch('events', batch2)
            expect(result2.size).toBe(1)
            expect(result2.has('token1:user1')).toBe(true)
        })

        it('different keys have independent rate limits', async () => {
            mockRedis.mget = jest.fn().mockResolvedValue([null, null])

            // Exhaust tokens for user1
            const batch1 = [createBatch('token1', 'user1', 15)]
            await service.handleEventBatch('events', batch1)

            // user2 should still have tokens
            mockRedis.mget = jest.fn().mockResolvedValue([null])
            const batch2 = [createBatch('token1', 'user2', 5)]
            const result = await service.handleEventBatch('events', batch2)

            expect(result.size).toBe(0)
        })
    })

    describe('healthCheck', () => {
        it('returns ok when Redis is healthy', async () => {
            const result = await service.healthCheck()

            expect(result.status).toBe('ok')
        })

        it('returns error when Redis fails', async () => {
            mockRedis.ping = jest.fn().mockRejectedValue(new Error('Connection refused'))

            const result = await service.healthCheck()

            expect(result.status).toBe('error')
        })
    })

    describe('shutdown', () => {
        it('clears local cache', async () => {
            // Populate cache
            mockRedis.mget = jest.fn().mockResolvedValue(['1'])
            await service.handleEventBatch('events', [createBatch('token1', 'user1', 1)])

            await service.shutdown()

            // After shutdown, cache should be cleared
            // Next call should hit Redis again
            mockRedis.mget = jest.fn().mockResolvedValue([null])
            await service.handleEventBatch('events', [createBatch('token1', 'user1', 1)])

            expect(mockRedis.mget).toHaveBeenCalled()
        })
    })
})
