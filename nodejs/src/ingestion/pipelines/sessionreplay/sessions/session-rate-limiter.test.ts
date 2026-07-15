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

    describe('handleMessage', () => {
        it('should allow events up to the limit', () => {
            const limiter = new SessionRateLimiter(3)
            const session: [number, string] = [123, 'session456']

            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.getEventCount(...session)).toBe(3)
        })

        it('should block messages after limit is exceeded', () => {
            const limiter = new SessionRateLimiter(2)
            const session: [number, string] = [123, 'session456']

            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.handleMessage(...session, 1)).toBe(false)
            expect(limiter.handleMessage(...session, 1)).toBe(false)
        })

        it('should track multiple sessions independently', () => {
            const limiter = new SessionRateLimiter(2)
            const session1: [number, string] = [123, 'session1']
            const session2: [number, string] = [123, 'session2']

            expect(limiter.handleMessage(...session1, 1)).toBe(true)
            expect(limiter.handleMessage(...session2, 1)).toBe(true)
            expect(limiter.handleMessage(...session1, 1)).toBe(true)
            expect(limiter.handleMessage(...session2, 1)).toBe(true)

            expect(limiter.handleMessage(...session1, 1)).toBe(false)
            expect(limiter.handleMessage(...session2, 1)).toBe(false)
        })

        it('should continue blocking after limit is hit', () => {
            const limiter = new SessionRateLimiter(1)
            const session: [number, string] = [123, 'session456']

            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.handleMessage(...session, 1)).toBe(false)
            expect(limiter.handleMessage(...session, 1)).toBe(false)
            expect(limiter.handleMessage(...session, 1)).toBe(false)
        })

        it('should handle messages with varying event counts', () => {
            const limiter = new SessionRateLimiter(10)
            const session: [number, string] = [123, 'session456']

            expect(limiter.handleMessage(...session, 3)).toBe(true)
            expect(limiter.getEventCount(...session)).toBe(3)

            expect(limiter.handleMessage(...session, 5)).toBe(true)
            expect(limiter.getEventCount(...session)).toBe(8)

            expect(limiter.handleMessage(...session, 2)).toBe(true)
            expect(limiter.getEventCount(...session)).toBe(10)

            expect(limiter.handleMessage(...session, 1)).toBe(false)
            expect(limiter.getEventCount(...session)).toBe(11)
        })

        it('should allow unlimited events with MAX_SAFE_INTEGER', () => {
            const limiter = new SessionRateLimiter(Number.MAX_SAFE_INTEGER)
            const session: [number, string] = [123, 'session456']

            for (let i = 0; i < 1000; i++) {
                expect(limiter.handleMessage(...session, 1000)).toBe(true)
            }
            expect(limiter.getEventCount(...session)).toBe(1000000)
        })
    })

    describe('getEventCount', () => {
        it('should return 0 for new session', () => {
            const limiter = new SessionRateLimiter(10)
            expect(limiter.getEventCount(123, 'session456')).toBe(0)
        })

        it('should return current count for tracked session', () => {
            const limiter = new SessionRateLimiter(10)
            const session: [number, string] = [123, 'session456']

            limiter.handleMessage(...session, 1)
            expect(limiter.getEventCount(...session)).toBe(1)

            limiter.handleMessage(...session, 2)
            expect(limiter.getEventCount(...session)).toBe(3)
        })

        it('should increment count even after limit is hit', () => {
            const limiter = new SessionRateLimiter(2)
            const session: [number, string] = [123, 'session456']

            limiter.handleMessage(...session, 1)
            limiter.handleMessage(...session, 1)
            expect(limiter.getEventCount(...session)).toBe(2)

            limiter.handleMessage(...session, 1)
            limiter.handleMessage(...session, 1)
            expect(limiter.getEventCount(...session)).toBe(4)
        })
    })

    describe('clear', () => {
        it('should clear all sessions', () => {
            const limiter = new SessionRateLimiter(10)
            const session1: [number, string] = [123, 'session1']
            const session2: [number, string] = [123, 'session2']

            limiter.handleMessage(...session1, 2)
            limiter.handleMessage(...session2, 1)

            expect(limiter.getEventCount(...session1)).toBe(2)
            expect(limiter.getEventCount(...session2)).toBe(1)

            limiter.clear()

            expect(limiter.getEventCount(...session1)).toBe(0)
            expect(limiter.getEventCount(...session2)).toBe(0)
        })

        it('should clear limited session status', () => {
            const limiter = new SessionRateLimiter(1)
            const session: [number, string] = [123, 'session456']

            limiter.handleMessage(...session, 1)
            expect(limiter.handleMessage(...session, 1)).toBe(false)

            limiter.clear()
            expect(limiter.handleMessage(...session, 1)).toBe(true)
        })
    })

    describe('edge cases', () => {
        it('should handle limit of 0', () => {
            const limiter = new SessionRateLimiter(0)
            const session: [number, string] = [123, 'session456']

            expect(limiter.handleMessage(...session, 1)).toBe(false)
            expect(limiter.getEventCount(...session)).toBe(1)
        })

        it('should handle limit of 1', () => {
            const limiter = new SessionRateLimiter(1)
            const session: [number, string] = [123, 'session456']

            expect(limiter.handleMessage(...session, 1)).toBe(true)
            expect(limiter.handleMessage(...session, 1)).toBe(false)
        })

        it('should handle many concurrent sessions', () => {
            const limiter = new SessionRateLimiter(5)
            const sessions = Array.from({ length: 100 }, (_, i): [number, string] => [123, `session${i}`])

            for (const session of sessions) {
                for (let i = 0; i < 5; i++) {
                    expect(limiter.handleMessage(...session, 1)).toBe(true)
                }
                expect(limiter.handleMessage(...session, 1)).toBe(false)
            }
        })
    })
})
