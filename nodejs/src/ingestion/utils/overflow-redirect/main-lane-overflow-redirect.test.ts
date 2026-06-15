import { HealthCheckResultOk } from '../../../types'
import { MainLaneOverflowRedirect, MainLaneOverflowRedirectConfig } from './main-lane-overflow-redirect'
import { OverflowEventBatch } from './overflow-redirect-service'
import { OverflowRedisRepository } from './overflow-redis-repository'

const createMockRepository = (): jest.Mocked<OverflowRedisRepository> => ({
    batchCheck: jest.fn().mockResolvedValue(new Map()),
    batchFlag: jest.fn().mockResolvedValue(undefined),
    batchRefreshTTL: jest.fn().mockResolvedValue(undefined),
    healthCheck: jest.fn().mockResolvedValue(new HealthCheckResultOk()),
})

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
    let mockRepository: jest.Mocked<OverflowRedisRepository>
    let service: MainLaneOverflowRedirect

    const createService = (overrides: Partial<MainLaneOverflowRedirectConfig> = {}): MainLaneOverflowRedirect => {
        return new MainLaneOverflowRedirect({
            redisRepository: mockRepository,
            localCacheTTLSeconds: 60,
            bucketCapacity: 10,
            replenishRate: 1,
            statefulEnabled: true,
            ...overrides,
        })
    }

    beforeEach(() => {
        mockRepository = createMockRepository()
        service = createService()
    })

    describe('handleEventBatch', () => {
        it('returns empty set when no events exceed rate limit', async () => {
            const batch = [createBatch('token1', 'user1', 5)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })

        it('returns keys that exceed rate limit', async () => {
            // Bucket capacity is 10, so 15 events should exceed
            const batch = [createBatch('token1', 'user1', 15)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
        })

        it('flags newly rate-limited keys in Redis', async () => {
            const batch = [createBatch('token1', 'user1', 15)]

            await service.handleEventBatch('events', batch)

            expect(mockRepository.batchFlag).toHaveBeenCalledWith('events', [{ token: 'token1', distinctId: 'user1' }])
        })

        it('checks Redis for keys not in local cache', async () => {
            const batch = [createBatch('token1', 'user1', 5)]

            await service.handleEventBatch('events', batch)

            expect(mockRepository.batchCheck).toHaveBeenCalledWith('events', [{ token: 'token1', distinctId: 'user1' }])
        })

        it('returns keys that are already flagged in Redis', async () => {
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', true]]))

            const batch = [createBatch('token1', 'user1', 1)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
        })

        it('uses local cache for subsequent calls', async () => {
            // First call: Redis says key is flagged
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', true]]))

            const batch1 = [createBatch('token1', 'user1', 1)]
            await service.handleEventBatch('events', batch1)

            // Reset mock
            mockRepository.batchCheck.mockClear()

            // Second call: should use cache, not repository
            const batch2 = [createBatch('token1', 'user1', 1)]
            const result = await service.handleEventBatch('events', batch2)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
            expect(mockRepository.batchCheck).not.toHaveBeenCalled()
        })

        it('caches negative results (not in Redis)', async () => {
            // First call: key not in Redis
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', false]]))

            const batch1 = [createBatch('token1', 'user1', 1)]
            await service.handleEventBatch('events', batch1)

            // Reset mock
            mockRepository.batchCheck.mockClear()
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', true]]))

            // Second call: should use cache (null), not check repository again
            const batch2 = [createBatch('token1', 'user1', 1)]
            await service.handleEventBatch('events', batch2)

            expect(mockRepository.batchCheck).not.toHaveBeenCalled()
        })

        it('handles multiple keys independently', async () => {
            mockRepository.batchCheck.mockResolvedValue(
                new Map([
                    ['token1:user1', false],
                    ['token1:user2', false],
                ])
            )

            const batch = [
                createBatch('token1', 'user1', 5), // Below limit
                createBatch('token1', 'user2', 15), // Exceeds limit
            ]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user2')).toBe(true)
            expect(result.has('token1:user1')).toBe(false)
        })

        it('batches all keys in a single batchCheck call', async () => {
            const batch = [
                createBatch('token1', 'user1', 1),
                createBatch('token1', 'user2', 1),
                createBatch('token2', 'user1', 1),
            ]

            await service.handleEventBatch('events', batch)

            expect(mockRepository.batchCheck).toHaveBeenCalledTimes(1)
            expect(mockRepository.batchCheck).toHaveBeenCalledWith('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
                { token: 'token2', distinctId: 'user1' },
            ])
        })
    })

    describe('fail-open behavior', () => {
        it('treats keys as not flagged when batchCheck returns all false (repository fail-open default)', async () => {
            // The repository layer handles Redis errors and returns defaults (all false)
            // Simulate repository fail-open by returning the default "not flagged" result
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', false]]))

            const batch = [createBatch('token1', 'user1', 5)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })

        it('still redirects based on rate limit even when batchFlag is a no-op', async () => {
            // Even if batchFlag does nothing (e.g. repository fail-open), the local
            // rate limit decision still causes a redirect for this batch
            const batch = [createBatch('token1', 'user1', 15)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(1)
            expect(result.has('token1:user1')).toBe(true)
        })
    })

    describe('rate limiting behavior', () => {
        it('rate limit state persists across batches', async () => {
            // First batch: consume 8 of 10 tokens
            const batch1 = [createBatch('token1', 'user1', 8)]
            const result1 = await service.handleEventBatch('events', batch1)
            expect(result1.size).toBe(0)

            // Second batch: consume 3 more tokens (total 11, exceeds 10)
            const batch2 = [createBatch('token1', 'user1', 3)]
            const result2 = await service.handleEventBatch('events', batch2)
            expect(result2.size).toBe(1)
            expect(result2.has('token1:user1')).toBe(true)
        })

        it('different keys have independent rate limits', async () => {
            // Exhaust tokens for user1
            const batch1 = [createBatch('token1', 'user1', 15)]
            await service.handleEventBatch('events', batch1)

            // user2 should still have tokens
            const batch2 = [createBatch('token1', 'user2', 5)]
            const result = await service.handleEventBatch('events', batch2)

            expect(result.size).toBe(0)
        })
    })

    describe('healthCheck', () => {
        it('delegates to repository', async () => {
            const result = await service.healthCheck()

            expect(result.status).toBe('ok')
            expect(mockRepository.healthCheck).toHaveBeenCalled()
        })
    })

    describe('shutdown', () => {
        it('clears local cache', async () => {
            // Populate cache
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', true]]))
            await service.handleEventBatch('events', [createBatch('token1', 'user1', 1)])

            await service.shutdown()

            // After shutdown, cache should be cleared
            // Next call should check repository again
            mockRepository.batchCheck.mockClear()
            mockRepository.batchCheck.mockResolvedValue(new Map([['token1:user1', false]]))
            await service.handleEventBatch('events', [createBatch('token1', 'user1', 1)])

            expect(mockRepository.batchCheck).toHaveBeenCalled()
        })
    })
})
