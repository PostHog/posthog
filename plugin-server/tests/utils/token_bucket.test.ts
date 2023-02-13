import { BucketKeyMissingError, Limiter, Storage } from '../../src/utils/token_bucket'

describe('Storage', () => {
    describe('replenish()', () => {
        afterEach(() => {
            jest.useRealTimers()
        })

        it('adds capacity to new key', () => {
            const key = 'test'
            const storage = new Storage(10, 1)
            const now = new Date('2023-02-08T08:00:00')
            jest.useFakeTimers().setSystemTime(now)

            storage.replenish(key)

            expect(storage.buckets.has(key)).toEqual(true)
            expect(storage.buckets.get(key)![0]).toEqual(10)
            expect(storage.buckets.get(key)![1]).toEqual(now.valueOf())
        })

        it('adds rate to existing key', () => {
            const key = 'test'
            const storage = new Storage(10, 1)
            const now = new Date('2023-02-08T08:00:00')
            jest.useFakeTimers().setSystemTime(now)

            storage.replenish(key)

            now.setSeconds(now.getSeconds() + 2)
            jest.setSystemTime(now)
            storage.replenish(key)

            expect(storage.buckets.has(key)).toEqual(true)
            expect(storage.buckets.get(key)![0]).toEqual(12)
            expect(storage.buckets.get(key)![1]).toEqual(now.valueOf())
        })

        it('adds rate to existing key with argument now', () => {
            const key = 'test'
            const storage = new Storage(10, 1)
            const now = Date.now()

            storage.replenish(key, now)
            storage.replenish(key, now + 2000)

            expect(storage.buckets.has(key)).toEqual(true)
            expect(storage.buckets.get(key)![0]).toEqual(12)
            expect(storage.buckets.get(key)![1]).toEqual(now + 2000)
        })
    })

    describe('consume()', () => {
        it('consumes when tokens are less than capacity', () => {
            const key = 'test'
            const storage = new Storage(10, 1)

            storage.replenish(key)

            expect(storage.consume(key, 9)).toEqual(true)
            expect(storage.buckets.get(key)![0]).toEqual(1)
        })

        it('rejects when tokens are more than capacity', () => {
            const key = 'test'
            const storage = new Storage(10, 1)

            storage.replenish(key)

            expect(storage.consume(key, 11)).toEqual(false)
            expect(storage.buckets.get(key)![0]).toEqual(10)
        })

        it('throws error on missing bucket key', () => {
            const key = 'test'
            const storage = new Storage(10, 1)

            expect(storage.buckets.has(key)).toEqual(false)
            expect(() => storage.consume(key, 1)).toThrow(BucketKeyMissingError)
        })
    })
})

describe('Limiter', () => {
    describe('consume()', () => {
        afterEach(() => {
            jest.useRealTimers()
        })

        it('consumes when tokens available', () => {
            const key = 'test'
            const limiter = new Limiter(10, 2)
            const now = new Date('2023-02-08T08:00:00')
            jest.useFakeTimers().setSystemTime(now)

            expect(limiter.consume(key, 9)).toEqual(true)
        })

        it('rejects when tokens run out', () => {
            const key = 'test'
            const limiter = new Limiter(10, 2)
            const now = new Date('2023-02-08T08:00:00')
            jest.useFakeTimers().setSystemTime(now)

            expect(limiter.consume(key, 10)).toEqual(true)
            // We are not advancing time, so no tokens should have been replenished
            expect(limiter.consume(key, 1)).toEqual(false)
        })

        it('consumes when tokens have been replenished', () => {
            const key = 'test'
            const limiter = new Limiter(10, 2)
            const now = new Date('2023-02-08T08:00:00')

            jest.useFakeTimers().setSystemTime(now)
            limiter.consume(key, 10)

            expect(limiter.consume(key, 1)).toEqual(false)

            jest.setSystemTime(now.valueOf() + 1000)
            // Now that we have advanced 1 second, we can consume 1 token
            expect(limiter.consume(key, 1)).toEqual(true)
        })

        it('consumes when tokens have been replenished with now argument', () => {
            const key = 'test'
            const limiter = new Limiter(10, 2)
            const now = new Date('2023-02-08T08:00:00')
            jest.useFakeTimers().setSystemTime(now)

            limiter.consume(key, 10, now.valueOf())
            expect(limiter.consume(key, 1)).toEqual(false)
            // Even though we are not advancing time, we are passing the time to use with now
            expect(limiter.consume(key, 1, now.valueOf() + 1000)).toEqual(true)
        })
    })
})
