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
            limiter = new MemoryRateLimiter(10, 2, 1000)
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
            expect(limiter.consume(key, 1)).toEqual(true)
        })

        it('consumes when tokens have been replenished with now argument', () => {
            limiter.consume(key, 10, now.valueOf())
            expect(limiter.consume(key, 1)).toEqual(false)
            expect(limiter.consume(key, 1, now.valueOf() + 1000)).toEqual(true)
        })

        it('evicts oldest bucket when max buckets exceeded', () => {
            const smallLimiter = new MemoryRateLimiter(10, 2, 2)

            expect(smallLimiter.consume('key1', 5)).toEqual(true)
            expect(smallLimiter.consume('key2', 5)).toEqual(true)
            expect(smallLimiter.buckets.size).toEqual(2)

            expect(smallLimiter.consume('key3', 5)).toEqual(true)
            expect(smallLimiter.buckets.size).toEqual(2)
            expect(smallLimiter.buckets.has('key1')).toEqual(false)
            expect(smallLimiter.buckets.has('key2')).toEqual(true)
            expect(smallLimiter.buckets.has('key3')).toEqual(true)
        })

        it('cache hits do not affect eviction order', () => {
            const smallLimiter = new MemoryRateLimiter(10, 2, 2)

            expect(smallLimiter.consume('key1', 5)).toEqual(true)
            expect(smallLimiter.consume('key2', 5)).toEqual(true)

            expect(smallLimiter.consume('key1', 1)).toEqual(true)

            expect(smallLimiter.consume('key3', 5)).toEqual(true)
            expect(smallLimiter.buckets.has('key1')).toEqual(false)
            expect(smallLimiter.buckets.has('key2')).toEqual(true)
            expect(smallLimiter.buckets.has('key3')).toEqual(true)
        })
    })
})
