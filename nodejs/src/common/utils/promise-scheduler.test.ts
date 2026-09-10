import { PromiseScheduler } from './promise-scheduler'

describe('PromiseScheduler', () => {
    let scheduler: PromiseScheduler

    beforeEach(() => {
        scheduler = new PromiseScheduler()
    })

    describe('schedule with a single promise', () => {
        it('should track the promise and remove it on resolve', async () => {
            let resolve: () => void
            const promise = new Promise<void>((r) => (resolve = r))

            void scheduler.schedule(promise)
            expect(scheduler.promises.size).toBe(1)

            resolve!()
            await promise
            await Promise.resolve()
            expect(scheduler.promises.size).toBe(0)
        })

        it('should remove the promise on rejection', async () => {
            let reject: (err: Error) => void
            const promise = new Promise<void>((_, r) => (reject = r))

            void scheduler.schedule(promise)
            expect(scheduler.promises.size).toBe(1)

            reject!(new Error('fail'))
            await promise.catch(() => {})
            await Promise.resolve()
            expect(scheduler.promises.size).toBe(0)
        })

        it('should return the same promise', () => {
            const original = Promise.resolve(42)
            const returned = scheduler.schedule(original)
            expect(returned).toBe(original)
        })
    })

    describe('schedule with multiple promises', () => {
        it('should track each promise individually', async () => {
            let resolve1: () => void
            let resolve2: () => void
            const p1 = new Promise<void>((r) => (resolve1 = r))
            const p2 = new Promise<void>((r) => (resolve2 = r))

            void scheduler.schedule(p1, p2)
            expect(scheduler.promises.size).toBe(2)

            resolve1!()
            await p1
            await Promise.resolve()
            expect(scheduler.promises.size).toBe(1)

            resolve2!()
            await p2
            await Promise.resolve()
            expect(scheduler.promises.size).toBe(0)
        })

        it('should return a combined result like Promise.all', async () => {
            const p1 = Promise.resolve('hello')
            const p2 = Promise.resolve(42)

            const result = await scheduler.schedule(p1, p2)
            expect(result).toEqual(['hello', 42])
        })

        it('should reject if any promise rejects', async () => {
            const p1 = Promise.resolve('ok')
            const p2 = Promise.reject(new Error('boom'))

            await expect(scheduler.schedule(p1, p2)).rejects.toThrow('boom')
        })

        it('should handle three or more promises', async () => {
            const p1 = Promise.resolve(1)
            const p2 = Promise.resolve('two')
            const p3 = Promise.resolve(true)

            const result = await scheduler.schedule(p1, p2, p3)
            expect(result).toEqual([1, 'two', true])
        })
    })

    describe('waitForAll', () => {
        it('should resolve immediately when no promises are tracked', async () => {
            await expect(scheduler.waitForAll()).resolves.toEqual([])
        })

        it('should wait for all scheduled promises', async () => {
            let resolve1: (v: string) => void
            let resolve2: (v: string) => void
            const p1 = new Promise<string>((r) => (resolve1 = r))
            const p2 = new Promise<string>((r) => (resolve2 = r))

            void scheduler.schedule(p1)
            void scheduler.schedule(p2)

            let allDone = false
            const waiting = scheduler.waitForAll().then(() => (allDone = true))

            resolve1!('a')
            await Promise.resolve()
            expect(allDone).toBe(false)

            resolve2!('b')
            await waiting
            expect(allDone).toBe(true)
        })
    })

    describe('waitForAllSettled', () => {
        it('should resolve even when some promises reject', async () => {
            void scheduler.schedule(Promise.resolve('ok'))
            void scheduler.schedule(Promise.reject(new Error('fail')).catch(() => {}))

            const results = await scheduler.waitForAllSettled()
            expect(results).toHaveLength(2)
        })
    })
})
