import { ResettableSignal } from './resettable-signal'

describe('ResettableSignal', () => {
    const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

    // Whether a promise has settled, decided by flushing pending microtasks.
    async function settled(promise: Promise<void>): Promise<boolean> {
        let done = false
        void promise.then(() => {
            done = true
        })
        await tick()
        return done
    }

    it('starts unresolved', async () => {
        const signal = new ResettableSignal()
        expect(await settled(signal.wait())).toBe(false)
    })

    it('resolve() resolves the current promise', async () => {
        const signal = new ResettableSignal()
        signal.resolve()
        expect(await settled(signal.wait())).toBe(true)
    })

    it('reset() arms a fresh, unresolved promise after a resolve', async () => {
        const signal = new ResettableSignal()
        signal.resolve()
        expect(await settled(signal.wait())).toBe(true)
        signal.reset()
        expect(await settled(signal.wait())).toBe(false)
    })

    it('reset() replaces the promise identity', () => {
        const signal = new ResettableSignal()
        const first = signal.wait()
        signal.reset()
        expect(signal.wait()).not.toBe(first)
    })

    it('a resolve() before reset() does not resolve the post-reset promise', async () => {
        // Models the pullProcessed race: a group resolves the OLD promise, then
        // the loop resets; the new promise must stay pending until the next resolve.
        const signal = new ResettableSignal()
        signal.resolve()
        signal.reset()
        const armed = signal.wait()
        expect(await settled(armed)).toBe(false)
        signal.resolve()
        expect(await settled(armed)).toBe(true)
    })

    it('resolve() is safe to call multiple times', async () => {
        const signal = new ResettableSignal()
        signal.resolve()
        expect(() => signal.resolve()).not.toThrow()
        expect(await settled(signal.wait())).toBe(true)
    })

    it('a promise captured before resolve() still settles', async () => {
        const signal = new ResettableSignal()
        const captured = signal.wait()
        signal.resolve()
        expect(await settled(captured)).toBe(true)
    })
})
