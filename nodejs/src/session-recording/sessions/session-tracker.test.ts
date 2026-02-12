import { Redis } from 'ioredis'

import { RedisPool } from '../../types'
import { SessionBatchMetrics } from './metrics'
import { SessionTracker } from './session-tracker'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementNewSessionsDetected: jest.fn(),
        incrementSessionTrackerCacheHit: jest.fn(),
        incrementSessionTrackerCacheMiss: jest.fn(),
        incrementSessionTrackerRedisErrors: jest.fn(),
    },
}))

describe('SessionTracker', () => {
    let sessionTracker: SessionTracker
    let mockRedisClient: jest.Mocked<Redis>
    let mockRedisPool: jest.Mocked<RedisPool>

    beforeEach(() => {
        jest.clearAllMocks()

        mockRedisClient = {
            set: jest.fn(),
        } as unknown as jest.Mocked<Redis>

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>
    })

    describe('trackSession', () => {
        it('should return true for new session when key does not exist', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            const isNew = await sessionTracker.trackSession(1, 'session-123')

            expect(isNew).toBe(true)
            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/session-seen:1:session-123',
                '1',
                'EX',
                48 * 60 * 60,
                'NX'
            )
            expect(SessionBatchMetrics.incrementNewSessionsDetected).toHaveBeenCalledTimes(1)
        })

        it('should return false when session already exists', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue(null)
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            const isNew = await sessionTracker.trackSession(1, 'session-123')

            expect(isNew).toBe(false)
            expect(SessionBatchMetrics.incrementNewSessionsDetected).not.toHaveBeenCalled()
        })

        it('should track sessions separately per team', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            await sessionTracker.trackSession(1, 'session-123')
            await sessionTracker.trackSession(2, 'session-123')

            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/session-seen:1:session-123',
                '1',
                'EX',
                48 * 60 * 60,
                'NX'
            )
            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/session-seen:2:session-123',
                '1',
                'EX',
                48 * 60 * 60,
                'NX'
            )
        })

        it('should fail open and return false on Redis set error', async () => {
            mockRedisClient.set = jest.fn().mockRejectedValue(new Error('Redis error'))
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            const isNew = await sessionTracker.trackSession(1, 'session-123')

            expect(isNew).toBe(false)
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
            expect(SessionBatchMetrics.incrementSessionTrackerRedisErrors).toHaveBeenCalled()
        })

        it('should fail open and return false on Redis acquire error', async () => {
            mockRedisPool.acquire = jest.fn().mockRejectedValue(new Error('Pool exhausted'))
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            const isNew = await sessionTracker.trackSession(1, 'session-123')

            expect(isNew).toBe(false)
            expect(SessionBatchMetrics.incrementSessionTrackerRedisErrors).toHaveBeenCalled()
            expect(mockRedisPool.release).not.toHaveBeenCalled()
        })

        it('should use 48 hour TTL', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            await sessionTracker.trackSession(1, 'session-123')

            const expectedTTL = 48 * 60 * 60
            expect(mockRedisClient.set).toHaveBeenCalledWith(expect.any(String), '1', 'EX', expectedTTL, 'NX')
        })
    })

    describe('local cache', () => {
        it('should return false from cache without calling Redis on second call', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            // First call should hit Redis
            const isNew1 = await sessionTracker.trackSession(1, 'session-123')
            expect(isNew1).toBe(true)
            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionTrackerCacheMiss).toHaveBeenCalledTimes(1)

            // Second call should use cache
            const isNew2 = await sessionTracker.trackSession(1, 'session-123')
            expect(isNew2).toBe(false)
            expect(mockRedisClient.set).toHaveBeenCalledTimes(1) // Still only 1 call
            expect(SessionBatchMetrics.incrementSessionTrackerCacheHit).toHaveBeenCalledTimes(1)
        })

        it('should cache sessions separately per team', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            await sessionTracker.trackSession(1, 'session-123')
            await sessionTracker.trackSession(2, 'session-123')

            // Both should have hit Redis (different teams)
            expect(mockRedisClient.set).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementSessionTrackerCacheMiss).toHaveBeenCalledTimes(2)

            // Now both should be cached
            await sessionTracker.trackSession(1, 'session-123')
            await sessionTracker.trackSession(2, 'session-123')

            expect(mockRedisClient.set).toHaveBeenCalledTimes(2) // No additional calls
            expect(SessionBatchMetrics.incrementSessionTrackerCacheHit).toHaveBeenCalledTimes(2)
        })

        it('should hit Redis again after cache TTL expires', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue(null) // Session already exists
            const shortCacheTtlMs = 50 // 50ms TTL for testing
            sessionTracker = new SessionTracker(mockRedisPool, shortCacheTtlMs)

            // First call
            await sessionTracker.trackSession(1, 'session-123')
            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)

            // Second call within TTL - should use cache
            await sessionTracker.trackSession(1, 'session-123')
            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)

            // Wait for TTL to expire
            await new Promise((resolve) => setTimeout(resolve, shortCacheTtlMs + 10))

            // Third call after TTL - should hit Redis again
            await sessionTracker.trackSession(1, 'session-123')
            expect(mockRedisClient.set).toHaveBeenCalledTimes(2)
        })

        it('should cache both new and existing sessions', async () => {
            sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)

            // New session
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            await sessionTracker.trackSession(1, 'new-session')
            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)

            // Existing session
            mockRedisClient.set = jest.fn().mockResolvedValue(null)
            await sessionTracker.trackSession(1, 'existing-session')
            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)

            // Both should now be cached
            mockRedisClient.set = jest.fn()
            await sessionTracker.trackSession(1, 'new-session')
            await sessionTracker.trackSession(1, 'existing-session')
            expect(mockRedisClient.set).not.toHaveBeenCalled()
        })
    })
})
