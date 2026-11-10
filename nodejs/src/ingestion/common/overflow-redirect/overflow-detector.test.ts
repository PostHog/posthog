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

        const at = (secondsAfterStart: number) => start + secondsAfterStart * 1000

        beforeEach(() => {
            limiter = new MemoryRateLimiter(capacity, replenishRate)
        })

        it('removes a bucket once the event time and the clock both pass its refill window', () => {
            limiter.consume('quiet', 10, at(0))
            limiter.removeRefilledBuckets(at(0))

            limiter.consume('active', 1, at(refillWindowSeconds))
            limiter.removeRefilledBuckets(at(refillWindowSeconds))

            expect([...limiter.buckets.keys()]).toEqual(['active'])
        })

        it('keeps an empty bucket and its decision while the event time stays inside its refill window', () => {
            limiter.consume('drained', 10, at(0))
            limiter.removeRefilledBuckets(at(0))

            limiter.consume('other', 1, at(refillWindowSeconds - 1))
            limiter.removeRefilledBuckets(at(refillWindowSeconds * 10))

            expect(limiter.buckets.has('drained')).toEqual(true)
            expect(limiter.consume('drained', 1, at(0))).toEqual(false)
        })

        it('keeps a bucket in token debt until the debt is refilled too', () => {
            limiter.consume('debt', capacity * 3, at(0))
            limiter.removeRefilledBuckets(at(0))

            limiter.consume('other', 1, at(refillWindowSeconds))
            limiter.removeRefilledBuckets(at(refillWindowSeconds))

            expect(limiter.buckets.has('debt')).toEqual(true)
            expect(limiter.consume('debt', 1, at(refillWindowSeconds))).toEqual(false)
        })

        it('keeps the bucket and its decision for a key that consumes on a lagging partition', () => {
            limiter.consume('lagging', 10, at(0))
            limiter.consume('current', 1, at(1000))
            limiter.removeRefilledBuckets(at(0))

            expect(limiter.consume('lagging', 1, at(2))).toEqual(true)
            limiter.consume('current', 1, at(1000 + refillWindowSeconds))
            limiter.removeRefilledBuckets(at(refillWindowSeconds))

            expect(limiter.buckets.has('lagging')).toEqual(true)
            expect(limiter.consume('lagging', 4, at(2))).toEqual(false)
        })

        it('sweeps at most once per refill window', () => {
            limiter.consume('a', 10, at(1))
            limiter.removeRefilledBuckets(at(1))
            limiter.consume('b', 1, at(1 + refillWindowSeconds))

            limiter.removeRefilledBuckets(at(1 + refillWindowSeconds) - 1)
            expect(limiter.buckets.has('a')).toEqual(true)

            limiter.removeRefilledBuckets(at(1 + refillWindowSeconds))
            expect(limiter.buckets.has('a')).toEqual(false)
        })
    })
})
