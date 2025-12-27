import { Redis } from 'ioredis'

import { RedisPool } from '../../../../types'
import { SessionBatchMetrics } from './metrics'
import { NewSessionCallback, SessionTracker } from './session-tracker'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementNewSessionsDetected: jest.fn(),
    },
}))

describe('SessionTracker', () => {
    let sessionTracker: SessionTracker
    let mockRedisClient: jest.Mocked<Redis>
    let mockRedisPool: jest.Mocked<RedisPool>
    let mockCallback: jest.MockedFunction<NewSessionCallback>

    beforeEach(() => {
        jest.clearAllMocks()

        mockRedisClient = {
            set: jest.fn(),
        } as unknown as jest.Mocked<Redis>

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>

        mockCallback = jest.fn().mockResolvedValue(undefined)
    })

    describe('trackSession', () => {
        it('should detect new session when key does not exist', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool)

            await sessionTracker.trackSession(1, 'session-123', mockCallback)

            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/session-seen:1:session-123',
                '1',
                'EX',
                48 * 60 * 60,
                'NX'
            )
            expect(mockCallback).toHaveBeenCalledWith(1, 'session-123')
            expect(SessionBatchMetrics.incrementNewSessionsDetected).toHaveBeenCalledTimes(1)
        })

        it('should not detect new session when key already exists', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue(null)
            sessionTracker = new SessionTracker(mockRedisPool)

            await sessionTracker.trackSession(1, 'session-123', mockCallback)

            expect(mockCallback).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementNewSessionsDetected).not.toHaveBeenCalled()
        })

        it('should invoke callback with teamId and sessionId', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            let receivedTeamId: number | undefined
            let receivedSessionId: string | undefined
            mockCallback = jest.fn().mockImplementation((teamId, sessionId) => {
                receivedTeamId = teamId
                receivedSessionId = sessionId
                return Promise.resolve()
            })
            sessionTracker = new SessionTracker(mockRedisPool)

            await sessionTracker.trackSession(1, 'session-123', mockCallback)

            expect(receivedTeamId).toBe(1)
            expect(receivedSessionId).toBe('session-123')
        })

        it('should track sessions separately per team', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool)

            await sessionTracker.trackSession(1, 'session-123', mockCallback)
            await sessionTracker.trackSession(2, 'session-123', mockCallback)

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

        it('should work without callback', async () => {
            mockRedisClient.set = jest.fn().mockResolvedValue('OK')
            sessionTracker = new SessionTracker(mockRedisPool)

            await sessionTracker.trackSession(1, 'session-123')

            expect(SessionBatchMetrics.incrementNewSessionsDetected).toHaveBeenCalledTimes(1)
        })

        it('should always release Redis client', async () => {
            mockRedisClient.set = jest.fn().mockRejectedValue(new Error('Redis error'))
            sessionTracker = new SessionTracker(mockRedisPool)

            await expect(sessionTracker.trackSession(1, 'session-123', mockCallback)).rejects.toThrow('Redis error')

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
