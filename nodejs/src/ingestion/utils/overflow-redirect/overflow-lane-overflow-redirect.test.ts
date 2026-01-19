import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { OverflowLaneOverflowRedirect, OverflowLaneOverflowRedirectConfig } from './overflow-lane-overflow-redirect'
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

describe('OverflowLaneOverflowRedirect', () => {
    let mockRedis: jest.Mocked<Partial<Redis>>
    let mockPool: GenericPool<Redis>
    let service: OverflowLaneOverflowRedirect

    const defaultConfig: OverflowLaneOverflowRedirectConfig = {
        redisPool: null as unknown as GenericPool<Redis>,
        redisTTLSeconds: 300,
    }

    beforeEach(() => {
        mockRedis = {
            pipeline: jest.fn().mockReturnValue({
                getex: jest.fn().mockReturnThis(),
                exec: jest.fn().mockResolvedValue([]),
            }),
            ping: jest.fn().mockResolvedValue('PONG'),
        }
        mockPool = createMockRedisPool(mockRedis)
        service = new OverflowLaneOverflowRedirect({
            ...defaultConfig,
            redisPool: mockPool,
        })
    })

    describe('handleEventBatch', () => {
        it('always returns empty set (no redirects from overflow lane)', async () => {
            const batch = [createBatch('token1', 'user1', 100), createBatch('token1', 'user2', 100)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })

        it('refreshes TTL using GETEX for all keys in batch', async () => {
            const mockPipeline = {
                getex: jest.fn().mockReturnThis(),
                exec: jest.fn().mockResolvedValue([]),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            const batch = [createBatch('token1', 'user1'), createBatch('token1', 'user2')]

            await service.handleEventBatch('events', batch)

            expect(mockPipeline.getex).toHaveBeenCalledWith('@posthog/stateful-overflow/events:token1:user1', 'EX', 300)
            expect(mockPipeline.getex).toHaveBeenCalledWith('@posthog/stateful-overflow/events:token1:user2', 'EX', 300)
            expect(mockPipeline.exec).toHaveBeenCalled()
        })

        it('uses correct Redis key format for different overflow types', async () => {
            const mockPipeline = {
                getex: jest.fn().mockReturnThis(),
                exec: jest.fn().mockResolvedValue([]),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            await service.handleEventBatch('recordings', [createBatch('token1', 'session1')])

            expect(mockPipeline.getex).toHaveBeenCalledWith(
                '@posthog/stateful-overflow/recordings:token1:session1',
                'EX',
                300
            )
        })

        it('handles empty batch gracefully', async () => {
            const result = await service.handleEventBatch('events', [])

            expect(result.size).toBe(0)
            expect(mockRedis.pipeline).not.toHaveBeenCalled()
        })

        it('batches all GETEX calls in single pipeline', async () => {
            const mockPipeline = {
                getex: jest.fn().mockReturnThis(),
                exec: jest.fn().mockResolvedValue([]),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            const batch = [
                createBatch('token1', 'user1'),
                createBatch('token1', 'user2'),
                createBatch('token2', 'user1'),
            ]

            await service.handleEventBatch('events', batch)

            // Should call pipeline once
            expect(mockRedis.pipeline).toHaveBeenCalledTimes(1)
            // Should queue 3 GETEX calls
            expect(mockPipeline.getex).toHaveBeenCalledTimes(3)
            // Should exec once
            expect(mockPipeline.exec).toHaveBeenCalledTimes(1)
        })
    })

    describe('fail-open behavior', () => {
        it('continues processing when Redis fails', async () => {
            const mockPipeline = {
                getex: jest.fn().mockReturnThis(),
                exec: jest.fn().mockRejectedValue(new Error('Redis error')),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            const batch = [createBatch('token1', 'user1')]

            // Should not throw
            const result = await service.handleEventBatch('events', batch)

            // Should still return empty set (no redirects)
            expect(result.size).toBe(0)
        })

        it('continues when pool acquire fails', async () => {
            mockPool.acquire = jest.fn().mockRejectedValue(new Error('Pool exhausted'))

            const batch = [createBatch('token1', 'user1')]

            // Should not throw
            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })
    })

    describe('GETEX behavior', () => {
        it('only refreshes TTL for existing keys (does not create new keys)', async () => {
            // GETEX returns null for non-existent keys but doesn't create them
            const mockPipeline = {
                getex: jest.fn().mockReturnThis(),
                exec: jest.fn().mockResolvedValue([
                    [null, null],
                    [null, '1'],
                ]),
            }
            mockRedis.pipeline = jest.fn().mockReturnValue(mockPipeline)

            const batch = [
                createBatch('token1', 'user1'), // Key doesn't exist
                createBatch('token1', 'user2'), // Key exists
            ]

            const result = await service.handleEventBatch('events', batch)

            // Still returns empty set regardless of whether keys exist
            expect(result.size).toBe(0)
            // Both keys had GETEX called
            expect(mockPipeline.getex).toHaveBeenCalledTimes(2)
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
        it('completes without error', async () => {
            await expect(service.shutdown()).resolves.toBeUndefined()
        })
    })
})
