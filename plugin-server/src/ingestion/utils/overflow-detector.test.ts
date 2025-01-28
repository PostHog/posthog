import { MemoryRateLimiter } from './overflow-detector'

describe('MemoryRateLimiter', () => {
    describe('consume()', () => {
        const key = 'test'
        let limiter: MemoryRateLimiter
        let now = new Date('2025-01-01T01:00:00')

        const advanceTime = (seconds: number) => {
            now = new Date(now.valueOf() + seconds * 1000)
            jest.useFakeTimers().setSystemTime(now)
        }

        beforeEach(() => {
            limiter = new MemoryRateLimiter(10, 2)
            jest.useFakeTimers().setSystemTime(now)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('consumes and returns true when tokens available', () => {
            expect(limiter.consume(key, 9)).toEqual(true)
        })

        it('returns false when tokens run out', () => {
            expect(limiter.consume(key, 10)).toEqual(true)
            expect(limiter.consume(key, 1)).toEqual(false)
        })

        it('consumes when tokens have been replenished', () => {
            limiter.consume(key, 10)

            expect(limiter.consume(key, 1)).toEqual(false)

            advanceTime(1)
            // Now that we have advanced 1 second, we can consume 1 token
            expect(limiter.consume(key, 1)).toEqual(true)
        })

        it('consumes when tokens have been replenished with now argument', () => {
            limiter.consume(key, 10, now.valueOf())
            expect(limiter.consume(key, 1)).toEqual(false)
            // Even though we are not advancing time, we are passing the time to use with now
            expect(limiter.consume(key, 1, now.valueOf() + 1000)).toEqual(true)
        })
    })
})
