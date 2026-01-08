import { RedisPool } from '../../types'
import { Limiter } from '../../utils/token-bucket'
import { SessionBatchMetrics } from './metrics'
import { SessionFilter } from './session-filter'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementSessionsBlocked: jest.fn(),
        incrementMessagesDroppedBlocked: jest.fn(),
        incrementSessionFilterCacheHit: jest.fn(),
        incrementSessionFilterCacheMiss: jest.fn(),
        incrementNewSessionsRateLimited: jest.fn(),
        incrementSessionFilterRedisErrors: jest.fn(),
    },
}))

describe('SessionFilter', () => {
    let sessionFilter: SessionFilter
    let mockRedis: { set: jest.Mock; exists: jest.Mock }
    let mockRedisPool: jest.Mocked<RedisPool>
    let mockSessionLimiter: jest.Mocked<Limiter>

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

        mockSessionLimiter = {
            consume: jest.fn().mockReturnValue(true),
        } as unknown as jest.Mocked<Limiter>

        sessionFilter = new SessionFilter({
            redisPool: mockRedisPool,
            sessionLimiter: mockSessionLimiter,
            rateLimitEnabled: true,
            localCacheTtlMs: 5 * 60 * 1000,
        })
    })

    describe('blocking via handleNewSession', () => {
        it('should set a key in Redis with TTL when rate limited', async () => {
            mockSessionLimiter.consume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedis.set).toHaveBeenCalledWith(
                '@posthog/replay/session-blocked:1:session-123',
                '1',
                'EX',
                48 * 60 * 60
            )
        })

        it('should increment metrics when blocking a session', async () => {
            mockSessionLimiter.consume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(SessionBatchMetrics.incrementSessionsBlocked).toHaveBeenCalled()
        })

        it('should acquire and release Redis connection', async () => {
            mockSessionLimiter.consume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedis)
        })

        it('should fail open on Redis error but still block locally', async () => {
            mockSessionLimiter.consume.mockReturnValue(false)
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
            expect(SessionBatchMetrics.incrementMessagesDroppedBlocked).toHaveBeenCalled()
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
            mockSessionLimiter.consume.mockReturnValue(false)
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
    })

    describe('key generation', () => {
        it('should generate unique keys for different teams', async () => {
            mockSessionLimiter.consume.mockReturnValue(false)

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
            mockSessionLimiter.consume.mockReturnValue(false)

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
            // Create with very short TTL
            const shortTtlFilter = new SessionFilter({
                redisPool: mockRedisPool,
                sessionLimiter: mockSessionLimiter,
                rateLimitEnabled: true,
                localCacheTtlMs: 10, // 10ms TTL
            })

            mockRedis.exists.mockResolvedValue(1)

            // First check - hits Redis
            await shortTtlFilter.isBlocked(1, 'session-123')
            expect(mockRedis.exists).toHaveBeenCalledTimes(1)

            // Wait for cache to expire
            await new Promise((resolve) => setTimeout(resolve, 20))

            // Second check - cache expired, should hit Redis again
            await shortTtlFilter.isBlocked(1, 'session-123')
            expect(mockRedis.exists).toHaveBeenCalledTimes(2)
        })
    })

    describe('handleNewSession', () => {
        it('should not block when limiter allows the session', async () => {
            mockSessionLimiter.consume.mockReturnValue(true)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockSessionLimiter.consume).toHaveBeenCalledWith('1', 1)
            expect(mockRedis.set).not.toHaveBeenCalled()
        })

        it('should block when limiter denies and rate limiting is enabled', async () => {
            mockSessionLimiter.consume.mockReturnValue(false)

            await sessionFilter.handleNewSession(1, 'session-123')

            expect(mockRedis.set).toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementNewSessionsRateLimited).toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementSessionsBlocked).toHaveBeenCalled()
        })

        it('should only increment metric but not block when rate limiting is disabled', async () => {
            const disabledFilter = new SessionFilter({
                redisPool: mockRedisPool,
                sessionLimiter: mockSessionLimiter,
                rateLimitEnabled: false,
                localCacheTtlMs: 5 * 60 * 1000,
            })
            mockSessionLimiter.consume.mockReturnValue(false)

            await disabledFilter.handleNewSession(1, 'session-123')

            expect(mockRedis.set).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementNewSessionsRateLimited).toHaveBeenCalled()
        })
    })
})
