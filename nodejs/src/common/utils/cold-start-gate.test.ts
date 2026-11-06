import { ColdStartGate } from './cold-start-gate'

const ORIGIN = 'https://origin.test'

// Reports whether a promise has settled by the time one macrotask has run.
async function settledWithinATick(promise: Promise<unknown>): Promise<boolean> {
    const pending = Symbol('pending')
    const tick = new Promise<typeof pending>((resolve) => setImmediate(() => resolve(pending)))
    return (await Promise.race([promise.then(() => 'settled'), tick])) !== pending
}

describe('ColdStartGate', () => {
    let now: number

    beforeEach(() => {
        now = 1_000_000
        jest.spyOn(Date, 'now').mockImplementation(() => now)
    })

    it('holds later requests behind the probe and releases them together once it has headers', async () => {
        const gate = new ColdStartGate(1000)

        const admission = await gate.acquire(ORIGIN)
        expect(admission.probe).toBe(true)
        const held = [gate.acquire(ORIGIN), gate.acquire(ORIGIN)]
        expect(await settledWithinATick(Promise.race(held))).toBe(false)

        gate.touch(ORIGIN)
        admission.release()
        expect((await Promise.all(held)).map((entry) => entry.probe)).toEqual([false, false])

        // The origin is warm now, so a new request starts at once and is not a probe.
        expect((await gate.acquire(ORIGIN)).probe).toBe(false)
    })

    it('makes the next waiter the probe when the probe fails', async () => {
        const gate = new ColdStartGate(1000)

        const failedProbe = await gate.acquire(ORIGIN)
        const waiter = gate.acquire(ORIGIN)
        failedProbe.release()
        const secondProbe = await waiter
        expect(secondProbe.probe).toBe(true)

        // The origin is still cold, so the second probe holds a new request until it releases.
        const heldBehindSecondProbe = gate.acquire(ORIGIN)
        expect(await settledWithinATick(heldBehindSecondProbe)).toBe(false)
        gate.touch(ORIGIN)
        secondProbe.release()
        expect(await settledWithinATick(heldBehindSecondProbe)).toBe(true)
    })

    it('rejects a held request with its own reason when its signal aborts', async () => {
        const gate = new ColdStartGate(1000)
        const controller = new AbortController()
        const reason = new Error('deadline')

        const admission = await gate.acquire(ORIGIN)
        const held = gate.acquire(ORIGIN, controller.signal)
        controller.abort(reason)

        await expect(held).rejects.toBe(reason)
        // The probe is unaffected, and a later request still waits for it.
        expect(await settledWithinATick(gate.acquire(ORIGIN))).toBe(false)
        admission.release()
    })

    it('counts an origin as warm until the idle timeout has passed since its last activity', async () => {
        const gate = new ColdStartGate(1000)
        gate.touch(ORIGIN)

        now += 999
        expect(await settledWithinATick(gate.acquire(ORIGIN))).toBe(true)

        now += 2
        const probe = await gate.acquire(ORIGIN)
        expect(probe.probe).toBe(true)
        expect(await settledWithinATick(gate.acquire(ORIGIN))).toBe(false)
        probe.release()
    })
})
