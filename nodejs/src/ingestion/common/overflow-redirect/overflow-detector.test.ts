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

    describe('removing refilled buckets', () => {
        const capacity = 10
        const replenishRate = 2
        const refillWindowSeconds = capacity / replenishRate
        const start = new Date('2025-01-01T01:00:00').valueOf()
        let limiter: MemoryRateLimiter

        const setClock = (secondsAfterStart: number) => {
            jest.setSystemTime(start + secondsAfterStart * 1000)
        }
        const eventTime = (secondsAfterStart: number) => start + secondsAfterStart * 1000

        beforeEach(() => {
            jest.useFakeTimers().setSystemTime(start)
            limiter = new MemoryRateLimiter(capacity, replenishRate)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('removes a bucket once the event time and the clock both pass its refill window', () => {
            limiter.consume('quiet', 10, eventTime(0))

            setClock(refillWindowSeconds)
            limiter.consume('active', 1, eventTime(refillWindowSeconds))

            expect([...limiter.buckets.keys()]).toEqual(['active'])
        })

        it('keeps an empty bucket and its decision while the event time stays inside its refill window', () => {
            limiter.consume('drained', 10, eventTime(0))

            setClock(refillWindowSeconds * 10)
            limiter.consume('other', 1, eventTime(refillWindowSeconds - 1))

            expect(limiter.buckets.has('drained')).toEqual(true)
            expect(limiter.consume('drained', 1, eventTime(0))).toEqual(false)
        })

        it('keeps the bucket and its decision for a key that consumes on a lagging partition', () => {
            limiter.consume('lagging', 10, eventTime(0))
            limiter.consume('current', 1, eventTime(1000))

            setClock(refillWindowSeconds - 1)
            expect(limiter.consume('lagging', 1, eventTime(2))).toEqual(true)
            setClock(refillWindowSeconds)
            limiter.consume('current', 1, eventTime(1000 + refillWindowSeconds))

            expect(limiter.buckets.has('lagging')).toEqual(true)
            expect(limiter.consume('lagging', 4, eventTime(2))).toEqual(false)
        })

        it('sweeps at most once per refill window', () => {
            setClock(1)
            limiter.consume('a', 10, eventTime(1))
            setClock(refillWindowSeconds)
            limiter.consume('b', 1, eventTime(refillWindowSeconds))
            expect(limiter.buckets.has('a')).toEqual(true)

            setClock(refillWindowSeconds * 2 - 1)
            limiter.consume('b', 1, eventTime(refillWindowSeconds * 2 - 1))
            expect(limiter.buckets.has('a')).toEqual(true)

            setClock(refillWindowSeconds * 2)
            limiter.consume('b', 1, eventTime(refillWindowSeconds * 2))
            expect(limiter.buckets.has('a')).toEqual(false)
        })
    })
})
