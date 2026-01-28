import { RedisPool } from '../../types'
import { Limiter } from '../../utils/token-bucket'
import { SessionBatchMetrics } from './metrics'
import { SessionFilter } from './session-filter'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementSessionsBlocked: jest.fn(),
        incrementSessionFilterCacheHit: jest.fn(),
        incrementSessionFilterCacheMiss: jest.fn(),
        incrementNewSessionsRateLimited: jest.fn(),
        incrementSessionFilterRedisErrors: jest.fn(),
    },
}))

jest.mock('../../utils/token-bucket')

describe('SessionFilter', () => {
    let sessionFilter: SessionFilter
    let mockRedis: { set: jest.Mock; exists: jest.Mock }
    let mockRedisPool: jest.Mocked<RedisPool>
    let mockConsume: jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()

        mockRedis = {
            set: jest.fn().mockResolvedValue('OK'),
            exists: jest.fn().mockResolvedValue(0),
        }

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedis),
            release: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<RedisPool>

        mockConsume = jest.fn().mockReturnValue(true)
        ;(Limiter as jest.Mock).mockImplementation(() => ({
            consume: mockConsume,
        }))

        sessionFilter = new SessionFilter({
            redisPool: mockRedisPool,
            bucketCapacity: 1000,
            bucketReplenishRate: 1,
            blockingEnabled: true,
            filterEnabled: true,
            localCacheTtlMs: 5 * 60 * 1000,
        })
    })

    describe('blocking via handleNewSession', () => {
        it('should set a key in Redis with TTL when rate limited', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedis.set).toHaveBeenCalledWith(
                '@posthog/replay/session-blocked:1:session-123',
                '1',
                'EX',
                48 * 60 * 60
            )
        })

        it('should increment metrics when blocking a session', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(SessionBatchMetrics.incrementSessionsBlocked).toHaveBeenCalled()
        })

        it('should acquire and release Redis connection', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedis)
        })

        it('should fail open on Redis error but still block locally', async () => {
            mockConsume.mockReturnValue(false)
            mockRedis.set.mockRejectedValue(new Error('Redis error'))

            // Should not throw - fails open
            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedis)
            expect(SessionBatchMetrics.incrementSessionFilterRedisErrors).toHaveBeenCalled()

            // Session should still be blocked locally (via cache set before Redis call)
            const isBlocked = await sessionFilter.isBlocked(1, 'session-123')
            expect(isBlocked).toBe(true)
            expect(SessionBatchMetrics.incrementSessionFilterCacheHit).toHaveBeenCalled()
        })
    })

    describe('isBlocked', () => {
        it('should return false for non-blocked session', async () => {
            mockRedis.exists.mockResolvedValue(0)

            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(false)
            expect(mockRedis.exists).toHaveBeenCalledWith('@posthog/replay/session-blocked:1:session-123')
        })

        it('should return true for blocked session in Redis', async () => {
            mockRedis.exists.mockResolvedValue(1)

            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(true)
        })

        it('should return true from cache without Redis call on subsequent checks for blocked sessions', async () => {
            mockRedis.exists.mockResolvedValue(1)

            // First call - hits Redis
            await sessionFilter.isBlocked(1, 'session-123')
            expect(mockRedis.exists).toHaveBeenCalledTimes(1)

            // Second call - should hit cache
            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(true)
            expect(mockRedis.exists).toHaveBeenCalledTimes(1) // Not called again
            expect(SessionBatchMetrics.incrementSessionFilterCacheHit).toHaveBeenCalled()
        })

        it('should return false from cache without Redis call on subsequent checks for non-blocked sessions', async () => {
            mockRedis.exists.mockResolvedValue(0)

            // First call - hits Redis
            await sessionFilter.isBlocked(1, 'session-123')
            expect(mockRedis.exists).toHaveBeenCalledTimes(1)

            // Second call - should hit cache
            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(false)
            expect(mockRedis.exists).toHaveBeenCalledTimes(1) // Not called again
            expect(SessionBatchMetrics.incrementSessionFilterCacheHit).toHaveBeenCalled()
        })

        it('should cache blocked sessions locally after blocking via handleNewSession', async () => {
            mockConsume.mockReturnValue(false)
            await sessionFilter.handleNewSession(1, 'session-123')

            // Now check if blocked - should hit local cache
            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(true)
            expect(mockRedis.exists).not.toHaveBeenCalled() // Used cache instead
            expect(SessionBatchMetrics.incrementSessionFilterCacheHit).toHaveBeenCalled()
        })

        it('should increment cache miss metric when checking Redis', async () => {
            mockRedis.exists.mockResolvedValue(0)

            await sessionFilter.isBlocked(1, 'new-session')

            expect(SessionBatchMetrics.incrementSessionFilterCacheMiss).toHaveBeenCalled()
        })

        it('should acquire and release Redis connection', async () => {
            mockRedis.exists.mockResolvedValue(0)

            await sessionFilter.isBlocked(1, 'session-123')

            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedis)
        })

        it('should fail open and return false on Redis error', async () => {
            mockRedis.exists.mockRejectedValue(new Error('Redis error'))

            // Should not throw - fails open and returns false
            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(false)
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedis)
            expect(SessionBatchMetrics.incrementSessionFilterRedisErrors).toHaveBeenCalled()
        })

        it('should fail open and return false on Redis acquire error', async () => {
            mockRedisPool.acquire.mockRejectedValue(new Error('Pool exhausted'))

            const result = await sessionFilter.isBlocked(1, 'session-123')

            expect(result).toBe(false)
            expect(SessionBatchMetrics.incrementSessionFilterRedisErrors).toHaveBeenCalled()
            // Release should not be called since acquire failed
            expect(mockRedisPool.release).not.toHaveBeenCalled()
        })

        it('should not cache result on Redis error so subsequent calls retry', async () => {
            // First call fails
            mockRedis.exists.mockRejectedValueOnce(new Error('Redis error'))
            const result1 = await sessionFilter.isBlocked(1, 'session-123')
            expect(result1).toBe(false)

            // Second call should retry Redis (not use cache)
            mockRedis.exists.mockResolvedValueOnce(1)
            const result2 = await sessionFilter.isBlocked(1, 'session-123')
            expect(result2).toBe(true)

            // Should have called Redis twice (no caching on error)
            expect(mockRedisPool.acquire).toHaveBeenCalledTimes(2)
        })
    })

    describe('key generation', () => {
        it('should generate unique keys for different teams', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')
            await sessionFilter.handleNewSession(2, 'session-123')

            expect(mockRedis.set).toHaveBeenCalledWith(
                '@posthog/replay/session-blocked:1:session-123',
                '1',
                'EX',
                expect.any(Number)
            )
            expect(mockRedis.set).toHaveBeenCalledWith(
                '@posthog/replay/session-blocked:2:session-123',
                '1',
                'EX',
                expect.any(Number)
            )
        })

        it('should generate unique keys for different sessions', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')
            await sessionFilter.handleNewSession(1, 'session-456')

            expect(mockRedis.set).toHaveBeenCalledWith(
                '@posthog/replay/session-blocked:1:session-123',
                '1',
                'EX',
                expect.any(Number)
            )
            expect(mockRedis.set).toHaveBeenCalledWith(
                '@posthog/replay/session-blocked:1:session-456',
                '1',
                'EX',
                expect.any(Number)
            )
        })
    })

    describe('local cache', () => {
        it('should respect custom cache TTL', async () => {
            // LRU cache uses performance.now() for TTL, which Jest doesn't mock by default
            const startTime = performance.now()
            let currentTime = startTime
            jest.spyOn(performance, 'now').mockImplementation(() => currentTime)

            const cacheTtlMs = 5 * 60 * 1000 // 5 minutes
            const shortTtlFilter = new SessionFilter({
                redisPool: mockRedisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: cacheTtlMs,
            })

            mockRedis.exists.mockResolvedValue(1)

            // First check - hits Redis
            await shortTtlFilter.isBlocked(1, 'session-123')
            expect(mockRedis.exists).toHaveBeenCalledTimes(1)

            // Advance mocked time past cache TTL
            currentTime = startTime + cacheTtlMs + 1000

            // Second check - cache expired, should hit Redis again
            await shortTtlFilter.isBlocked(1, 'session-123')
            expect(mockRedis.exists).toHaveBeenCalledTimes(2)

            jest.restoreAllMocks()
        })
    })

    describe('handleNewSession', () => {
        it('should not block when limiter allows the session', async () => {
            mockConsume.mockReturnValue(true)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockConsume).toHaveBeenCalledWith('1', 1)
            expect(mockRedis.set).not.toHaveBeenCalled()
        })

        it('should block when limiter denies and rate limiting is enabled', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedis.set).toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementNewSessionsRateLimited).toHaveBeenCalledWith(1)
            expect(SessionBatchMetrics.incrementSessionsBlocked).toHaveBeenCalled()
        })

        it('should only increment metric but not block when blocking is disabled (dry run)', async () => {
            const disabledFilter = new SessionFilter({
                redisPool: mockRedisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: false,
                filterEnabled: true,
                localCacheTtlMs: 5 * 60 * 1000,
            })
            mockConsume.mockReturnValue(false)

            await disabledFilter.handleNewSession(1, 'session-123')

            expect(mockRedis.set).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementNewSessionsRateLimited).toHaveBeenCalledWith(1)
        })

        it('should skip all Redis calls when filter is disabled', async () => {
            const disabledFilter = new SessionFilter({
                redisPool: mockRedisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: true,
                filterEnabled: false,
                localCacheTtlMs: 5 * 60 * 1000,
            })
            mockConsume.mockReturnValue(false)

            // handleNewSession should not call Redis when filter is disabled
            await disabledFilter.handleNewSession(1, 'session-123')
            expect(mockRedis.set).not.toHaveBeenCalled()

            // isBlocked should return false immediately without Redis
            const isBlocked = await disabledFilter.isBlocked(1, 'session-123')
            expect(isBlocked).toBe(false)
            expect(mockRedis.exists).not.toHaveBeenCalled()
        })

        it('should fail open on Redis acquire error during blocking', async () => {
            mockConsume.mockReturnValue(false)
            mockRedisPool.acquire.mockRejectedValue(new Error('Pool exhausted'))

            // Should not throw
            await sessionFilter.handleNewSession(1, 'session-123')

            expect(SessionBatchMetrics.incrementSessionFilterRedisErrors).toHaveBeenCalled()
            // Session should still be blocked locally
            const isBlocked = await sessionFilter.isBlocked(1, 'session-123')
            expect(isBlocked).toBe(true)
        })

        it('should consume from limiter on each call even for same session', async () => {
            mockConsume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')
            await sessionFilter.handleNewSession(1, 'session-123')

            // Limiter is consumed each time - the limiter handles deduplication if needed
            expect(mockConsume).toHaveBeenCalledTimes(2)
            // Redis set is also called twice - this is fine since SET is idempotent at Redis level
            expect(mockRedis.set).toHaveBeenCalledTimes(2)
        })

        it('should not increment rate limited metric when limiter allows', async () => {
            mockConsume.mockReturnValue(true)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(SessionBatchMetrics.incrementNewSessionsRateLimited).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementSessionsBlocked).not.toHaveBeenCalled()
        })
    })

    describe('configuration', () => {
        it('should use custom cache max size', async () => {
            const smallCacheFilter = new SessionFilter({
                redisPool: mockRedisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 5 * 60 * 1000,
                localCacheMaxSize: 2,
            })

            mockRedis.exists.mockResolvedValue(0)

            // Fill cache with 2 entries
            await smallCacheFilter.isBlocked(1, 'session-1')
            await smallCacheFilter.isBlocked(1, 'session-2')

            // Third entry should evict the first
            await smallCacheFilter.isBlocked(1, 'session-3')

            jest.clearAllMocks()

            // First session should require Redis call again (was evicted)
            await smallCacheFilter.isBlocked(1, 'session-1')
            expect(mockRedisPool.acquire).toHaveBeenCalled()
        })
    })
})
