import { Redis } from 'ioredis'

import { RedisPool } from '../../../../types'
import { SessionBatchMetrics } from './metrics'
import { SessionTracker } from './session-tracker'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementNewSessionsDetected: jest.fn(),
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
            sessionTracker = new SessionTracker(mockRedisPool)

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
            sessionTracker = new SessionTracker(mockRedisPool)

            const isNew = await sessionTracker.trackSession(1, 'session-123')

            expect(isNew).toBe(false)
            expect(SessionBatchMetrics.incrementNewSessionsDetected).not.toHaveBeenCalled()
        })

        it('should track sessions separately per team', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool)

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

        it('should always release Redis client', async () => {
            mockRedisClient.set = jest.fn().mockRejectedValue(new Error('Redis error'))
            sessionTracker = new SessionTracker(mockRedisPool)

            await expect(sessionTracker.trackSession(1, 'session-123')).rejects.toThrow('Redis error')

            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
        })

        it('should use 48 hour TTL', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool)

            await sessionTracker.trackSession(1, 'session-123')

            const expectedTTL = 48 * 60 * 60
            expect(mockRedisClient.set).toHaveBeenCalledWith(expect.any(String), '1', 'EX', expectedTTL, 'NX')
        })
    })
})
