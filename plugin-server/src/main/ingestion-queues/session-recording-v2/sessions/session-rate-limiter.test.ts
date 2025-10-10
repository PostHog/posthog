import { SessionRateLimiter } from './session-rate-limiter'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementSessionsRateLimited: jest.fn(),
        incrementEventsRateLimited: jest.fn(),
    },
}))

describe('SessionRateLimiter', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('handleEvent', () => {
        it('should allow events up to the limit', () => {
            const limiter = new SessionRateLimiter(3)
            const sessionKey = 'team123$session456'

            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.getEventCount(sessionKey)).toBe(3)
        })

        it('should block events after limit is exceeded', () => {
            const limiter = new SessionRateLimiter(2)
            const sessionKey = 'team123$session456'

            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
        })

        it('should track multiple sessions independently', () => {
            const limiter = new SessionRateLimiter(2)
            const session1 = 'team123$session1'
            const session2 = 'team123$session2'

            expect(limiter.handleEvent(session1, 1)).toBe(true)
            expect(limiter.handleEvent(session2, 1)).toBe(true)
            expect(limiter.handleEvent(session1, 1)).toBe(true)
            expect(limiter.handleEvent(session2, 1)).toBe(true)

            expect(limiter.handleEvent(session1, 1)).toBe(false)
            expect(limiter.handleEvent(session2, 1)).toBe(false)
        })

        it('should continue blocking after limit is hit', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
        })

        it('should allow unlimited events with MAX_SAFE_INTEGER', () => {
            const limiter = new SessionRateLimiter(Number.MAX_SAFE_INTEGER)
            const sessionKey = 'team123$session456'

            for (let i = 0; i < 1000000; i++) {
                expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            }
            expect(limiter.getEventCount(sessionKey)).toBe(1000000)
        })
    })

    describe('getEventCount', () => {
        it('should return 0 for new session', () => {
            const limiter = new SessionRateLimiter(10)
            expect(limiter.getEventCount('team123$session456')).toBe(0)
        })

        it('should return current count for tracked session', () => {
            const limiter = new SessionRateLimiter(10)
            const sessionKey = 'team123$session456'

            limiter.handleEvent(sessionKey, 1)
            expect(limiter.getEventCount(sessionKey)).toBe(1)

            limiter.handleEvent(sessionKey, 1)
            limiter.handleEvent(sessionKey, 1)
            expect(limiter.getEventCount(sessionKey)).toBe(3)
        })

        it('should increment count even after limit is hit', () => {
            const limiter = new SessionRateLimiter(2)
            const sessionKey = 'team123$session456'

            limiter.handleEvent(sessionKey, 1)
            limiter.handleEvent(sessionKey, 1)
            expect(limiter.getEventCount(sessionKey)).toBe(2)

            limiter.handleEvent(sessionKey, 1)
            limiter.handleEvent(sessionKey, 1)
            expect(limiter.getEventCount(sessionKey)).toBe(4)
        })
    })

    describe('removeSession', () => {
        it('should remove session tracking', () => {
            const limiter = new SessionRateLimiter(10)
            const sessionKey = 'team123$session456'

            limiter.handleEvent(sessionKey, 1)
            limiter.handleEvent(sessionKey, 1)
            expect(limiter.getEventCount(sessionKey)).toBe(2)

            limiter.removeSession(sessionKey)
            expect(limiter.getEventCount(sessionKey)).toBe(0)

            limiter.handleEvent(sessionKey, 1)
            expect(limiter.getEventCount(sessionKey)).toBe(1)
        })

        it('should remove limited session status', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            limiter.handleEvent(sessionKey, 1)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)

            limiter.removeSession(sessionKey)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
        })

        it('should handle removing non-existent session', () => {
            const limiter = new SessionRateLimiter(10)
            expect(() => limiter.removeSession('nonexistent')).not.toThrow()
        })
    })

    describe('clear', () => {
        it('should clear all sessions', () => {
            const limiter = new SessionRateLimiter(10)
            const session1 = 'team123$session1'
            const session2 = 'team123$session2'

            limiter.handleEvent(session1, 1)
            limiter.handleEvent(session1, 1)
            limiter.handleEvent(session2, 1)

            expect(limiter.getEventCount(session1)).toBe(2)
            expect(limiter.getEventCount(session2)).toBe(1)

            limiter.clear()

            expect(limiter.getEventCount(session1)).toBe(0)
            expect(limiter.getEventCount(session2)).toBe(0)
        })

        it('should clear limited session status', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            limiter.handleEvent(sessionKey, 1)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)

            limiter.clear()
            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
        })
    })

    describe('edge cases', () => {
        it('should handle limit of 0', () => {
            const limiter = new SessionRateLimiter(0)
            const sessionKey = 'team123$session456'

            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
            expect(limiter.getEventCount(sessionKey)).toBe(1)
        })

        it('should handle limit of 1', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            expect(limiter.handleEvent(sessionKey, 1)).toBe(true)
            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)
        })

        it('should handle many concurrent sessions', () => {
            const limiter = new SessionRateLimiter(5)
            const sessions = Array.from({ length: 100 }, (_, i) => `team123$session${i}`)

            for (const session of sessions) {
                for (let i = 0; i < 5; i++) {
                    expect(limiter.handleEvent(session, 1)).toBe(true)
                }
                expect(limiter.handleEvent(session, 1)).toBe(false)
            }
        })
    })

    describe('discardPartition', () => {
        it('should remove all sessions for a partition', () => {
            const limiter = new SessionRateLimiter(10)
            const session1 = 'team123$session1'
            const session2 = 'team123$session2'
            const session3 = 'team123$session3'

            limiter.handleEvent(session1, 1)
            limiter.handleEvent(session1, 1)
            limiter.handleEvent(session2, 1)
            limiter.handleEvent(session3, 2)

            expect(limiter.getEventCount(session1)).toBe(2)
            expect(limiter.getEventCount(session2)).toBe(1)
            expect(limiter.getEventCount(session3)).toBe(1)

            limiter.discardPartition(1)

            expect(limiter.getEventCount(session1)).toBe(0)
            expect(limiter.getEventCount(session2)).toBe(0)
            expect(limiter.getEventCount(session3)).toBe(1)
        })

        it('should remove limited session status for partition', () => {
            const limiter = new SessionRateLimiter(1)
            const session1 = 'team123$session1'
            const session2 = 'team123$session2'

            limiter.handleEvent(session1, 1)
            limiter.handleEvent(session1, 1)
            limiter.handleEvent(session2, 2)
            limiter.handleEvent(session2, 2)

            expect(limiter.handleEvent(session1, 1)).toBe(false)
            expect(limiter.handleEvent(session2, 2)).toBe(false)

            limiter.discardPartition(1)

            expect(limiter.handleEvent(session1, 1)).toBe(true)
            expect(limiter.handleEvent(session2, 2)).toBe(false)
        })

        it('should handle discarding non-existent partition', () => {
            const limiter = new SessionRateLimiter(10)
            expect(() => limiter.discardPartition(999)).not.toThrow()
        })

        it('should allow session to restart on new partition after discard', () => {
            const limiter = new SessionRateLimiter(2)
            const sessionKey = 'team123$session456'

            limiter.handleEvent(sessionKey, 1)
            limiter.handleEvent(sessionKey, 1)
            limiter.handleEvent(sessionKey, 1)

            expect(limiter.handleEvent(sessionKey, 1)).toBe(false)

            limiter.discardPartition(1)

            limiter.handleEvent(sessionKey, 2)
            limiter.handleEvent(sessionKey, 2)
            expect(limiter.getEventCount(sessionKey)).toBe(2)
            expect(limiter.handleEvent(sessionKey, 2)).toBe(false)
        })
    })
})
