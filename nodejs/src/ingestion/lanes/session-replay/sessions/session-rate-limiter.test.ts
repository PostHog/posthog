import { ParsedMessageData } from '../kafka/types'
import { SessionRateLimiter } from './session-rate-limiter'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementSessionsRateLimited: jest.fn(),
        incrementEventsRateLimited: jest.fn(),
    },
}))

const createMessage = (eventCount: number): ParsedMessageData => {
    const events = Array.from({ length: eventCount }, (_, i) => ({ timestamp: i }))
    return {
        eventsByWindowId: { window1: events },
    } as any
}

describe('SessionRateLimiter', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('handleMessage', () => {
        it('should allow events up to the limit', () => {
            const limiter = new SessionRateLimiter(3)
            const sessionKey = 'team123$session456'

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.getEventCount(sessionKey)).toBe(3)
        })

        it('should block messages after limit is exceeded', () => {
            const limiter = new SessionRateLimiter(2)
            const sessionKey = 'team123$session456'

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
        })

        it('should track multiple sessions independently', () => {
            const limiter = new SessionRateLimiter(2)
            const session1 = 'team123$session1'
            const session2 = 'team123$session2'

            expect(limiter.handleMessage(session1, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(session2, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(session1, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(session2, 1, createMessage(1))).toBe(true)

            expect(limiter.handleMessage(session1, 1, createMessage(1))).toBe(false)
            expect(limiter.handleMessage(session2, 1, createMessage(1))).toBe(false)
        })

        it('should continue blocking after limit is hit', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
        })

        it('should count events across multiple windows', () => {
            const limiter = new SessionRateLimiter(5)
            const sessionKey = 'team123$session456'

            const messageWithMultipleWindows = {
                eventsByWindowId: {
                    window1: [{ timestamp: 1 }, { timestamp: 2 }],
                    window2: [{ timestamp: 3 }, { timestamp: 4 }],
                },
            } as any

            expect(limiter.handleMessage(sessionKey, 1, messageWithMultipleWindows)).toBe(true)
            expect(limiter.getEventCount(sessionKey)).toBe(4)
        })

        it('should handle messages with varying event counts', () => {
            const limiter = new SessionRateLimiter(10)
            const sessionKey = 'team123$session456'

            expect(limiter.handleMessage(sessionKey, 1, createMessage(3))).toBe(true)
            expect(limiter.getEventCount(sessionKey)).toBe(3)

            expect(limiter.handleMessage(sessionKey, 1, createMessage(5))).toBe(true)
            expect(limiter.getEventCount(sessionKey)).toBe(8)

            expect(limiter.handleMessage(sessionKey, 1, createMessage(2))).toBe(true)
            expect(limiter.getEventCount(sessionKey)).toBe(10)

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
            expect(limiter.getEventCount(sessionKey)).toBe(11)
        })

        it('should allow unlimited events with MAX_SAFE_INTEGER', () => {
            const limiter = new SessionRateLimiter(Number.MAX_SAFE_INTEGER)
            const sessionKey = 'team123$session456'

            for (let i = 0; i < 1000; i++) {
                expect(limiter.handleMessage(sessionKey, 1, createMessage(1000))).toBe(true)
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

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            expect(limiter.getEventCount(sessionKey)).toBe(1)

            limiter.handleMessage(sessionKey, 1, createMessage(2))
            expect(limiter.getEventCount(sessionKey)).toBe(3)
        })

        it('should increment count even after limit is hit', () => {
            const limiter = new SessionRateLimiter(2)
            const sessionKey = 'team123$session456'

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            limiter.handleMessage(sessionKey, 1, createMessage(1))
            expect(limiter.getEventCount(sessionKey)).toBe(2)

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            limiter.handleMessage(sessionKey, 1, createMessage(1))
            expect(limiter.getEventCount(sessionKey)).toBe(4)
        })
    })

    describe('removeSession', () => {
        it('should remove session tracking', () => {
            const limiter = new SessionRateLimiter(10)
            const sessionKey = 'team123$session456'

            limiter.handleMessage(sessionKey, 1, createMessage(2))
            expect(limiter.getEventCount(sessionKey)).toBe(2)

            limiter.removeSession(sessionKey)
            expect(limiter.getEventCount(sessionKey)).toBe(0)

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            expect(limiter.getEventCount(sessionKey)).toBe(1)
        })

        it('should remove limited session status', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)

            limiter.removeSession(sessionKey)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
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

            limiter.handleMessage(session1, 1, createMessage(2))
            limiter.handleMessage(session2, 1, createMessage(1))

            expect(limiter.getEventCount(session1)).toBe(2)
            expect(limiter.getEventCount(session2)).toBe(1)

            limiter.clear()

            expect(limiter.getEventCount(session1)).toBe(0)
            expect(limiter.getEventCount(session2)).toBe(0)
        })

        it('should clear limited session status', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)

            limiter.clear()
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
        })
    })

    describe('edge cases', () => {
        it('should handle limit of 0', () => {
            const limiter = new SessionRateLimiter(0)
            const sessionKey = 'team123$session456'

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
            expect(limiter.getEventCount(sessionKey)).toBe(1)
        })

        it('should handle limit of 1', () => {
            const limiter = new SessionRateLimiter(1)
            const sessionKey = 'team123$session456'

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)
        })

        it('should handle many concurrent sessions', () => {
            const limiter = new SessionRateLimiter(5)
            const sessions = Array.from({ length: 100 }, (_, i) => `team123$session${i}`)

            for (const session of sessions) {
                for (let i = 0; i < 5; i++) {
                    expect(limiter.handleMessage(session, 1, createMessage(1))).toBe(true)
                }
                expect(limiter.handleMessage(session, 1, createMessage(1))).toBe(false)
            }
        })
    })

    describe('discardPartition', () => {
        it('should remove all sessions for a partition', () => {
            const limiter = new SessionRateLimiter(10)
            const session1 = 'team123$session1'
            const session2 = 'team123$session2'
            const session3 = 'team123$session3'

            limiter.handleMessage(session1, 1, createMessage(2))
            limiter.handleMessage(session2, 1, createMessage(1))
            limiter.handleMessage(session3, 2, createMessage(1))

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

            limiter.handleMessage(session1, 1, createMessage(1))
            limiter.handleMessage(session1, 1, createMessage(1))
            limiter.handleMessage(session2, 2, createMessage(1))
            limiter.handleMessage(session2, 2, createMessage(1))

            expect(limiter.handleMessage(session1, 1, createMessage(1))).toBe(false)
            expect(limiter.handleMessage(session2, 2, createMessage(1))).toBe(false)

            limiter.discardPartition(1)

            expect(limiter.handleMessage(session1, 1, createMessage(1))).toBe(true)
            expect(limiter.handleMessage(session2, 2, createMessage(1))).toBe(false)
        })

        it('should handle discarding non-existent partition', () => {
            const limiter = new SessionRateLimiter(10)
            expect(() => limiter.discardPartition(999)).not.toThrow()
        })

        it('should allow session to restart on new partition after discard', () => {
            const limiter = new SessionRateLimiter(2)
            const sessionKey = 'team123$session456'

            limiter.handleMessage(sessionKey, 1, createMessage(1))
            limiter.handleMessage(sessionKey, 1, createMessage(1))
            limiter.handleMessage(sessionKey, 1, createMessage(1))

            expect(limiter.handleMessage(sessionKey, 1, createMessage(1))).toBe(false)

            limiter.discardPartition(1)

            limiter.handleMessage(sessionKey, 2, createMessage(1))
            limiter.handleMessage(sessionKey, 2, createMessage(1))
            expect(limiter.getEventCount(sessionKey)).toBe(2)
            expect(limiter.handleMessage(sessionKey, 2, createMessage(1))).toBe(false)
        })
    })
})
