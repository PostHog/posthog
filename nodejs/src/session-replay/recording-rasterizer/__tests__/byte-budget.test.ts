import { ByteBudget } from '~/session-replay/recording-rasterizer/capture/byte-budget'

// Lets queued grants resolve before the test inspects them.
const flush = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

function track(promise: Promise<() => void>): { granted: () => boolean; release: () => void } {
    let release: (() => void) | null = null
    promise.then(
        (fn) => (release = fn),
        () => {}
    )
    return {
        granted: () => release !== null,
        release: () => release!(),
    }
}

const MAX_WAIT_MS = 60_000

describe('ByteBudget', () => {
    beforeEach(() => {
        jest.useFakeTimers({ doNotFake: ['setImmediate'] })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('grants requests that fit and holds a request that does not fit until bytes are released', async () => {
        const budget = new ByteBudget(100, MAX_WAIT_MS)
        const a = track(budget.acquire(60))
        const b = track(budget.acquire(40))
        const c = track(budget.acquire(10))
        await flush()
        expect([a.granted(), b.granted(), c.granted()]).toEqual([true, true, false])

        a.release()
        await flush()
        expect(c.granted()).toBe(true)
        expect(budget.inFlightBytes).toBe(50)
    })

    it('runs a request larger than the budget alone, and queues later requests behind it', async () => {
        const budget = new ByteBudget(100, MAX_WAIT_MS)
        const small = track(budget.acquire(10))
        const large = track(budget.acquire(500))
        const later = track(budget.acquire(10))
        await flush()
        expect([small.granted(), large.granted(), later.granted()]).toEqual([true, false, false])

        small.release()
        await flush()
        expect([large.granted(), later.granted()]).toEqual([true, false])

        large.release()
        await flush()
        expect(later.granted()).toBe(true)
    })

    it('drops an aborted request from the queue so the next one is granted', async () => {
        const budget = new ByteBudget(100, MAX_WAIT_MS)
        const holder = track(budget.acquire(90))
        const controller = new AbortController()
        const aborted = budget.acquire(500, controller.signal)
        const next = track(budget.acquire(10))
        await flush()
        expect(next.granted()).toBe(false)

        controller.abort(new Error('cancelled'))
        await expect(aborted).rejects.toThrow('cancelled')
        await flush()
        expect(next.granted()).toBe(true)
        expect(holder.granted()).toBe(true)
    })

    it('ignores a second release of the same grant', async () => {
        const budget = new ByteBudget(100, MAX_WAIT_MS)
        const a = track(budget.acquire(60))
        const b = track(budget.acquire(30))
        await flush()

        a.release()
        a.release()
        expect(budget.inFlightBytes).toBe(30)
        b.release()
        expect(budget.inFlightBytes).toBe(0)
    })

    it('grants every queued request once it has waited the max wait, even when a grant is never released', async () => {
        const budget = new ByteBudget(100, MAX_WAIT_MS)
        track(budget.acquire(100))
        const large = track(budget.acquire(500))
        const small = track(budget.acquire(10))

        jest.advanceTimersByTime(MAX_WAIT_MS - 1)
        await flush()
        expect([large.granted(), small.granted()]).toEqual([false, false])

        jest.advanceTimersByTime(1)
        await flush()
        expect([large.granted(), small.granted()]).toEqual([true, true])
        expect(budget.inFlightBytes).toBe(610)
    })
})
