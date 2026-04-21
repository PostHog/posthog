import { afterMount, kea, listeners, path } from 'kea'

import { initKeaTests } from '~/test/init'

/**
 * Minimal logic used only to exercise the disposables plugin lifecycle.
 * We expose the cache directly so tests can poke at it after unmount.
 */
const testDisposablesLogic = kea<any>([path(['test', 'kea-disposables']), listeners(() => ({})), afterMount(() => {})])

describe('kea-disposables plugin', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('exposes a manager on cache.disposables after mount', () => {
        const logic = testDisposablesLogic()
        logic.mount()
        expect(logic.cache.disposables).toBeTruthy()
        expect(typeof logic.cache.disposables.add).toBe('function')
        expect(typeof logic.cache.disposables.dispose).toBe('function')
        expect(logic.cache.disposables.disposed).toBe(false)
        logic.unmount()
    })

    it('runs registered cleanup on unmount', () => {
        const cleanup = jest.fn()
        const logic = testDisposablesLogic()
        logic.mount()
        logic.cache.disposables.add(() => cleanup, 'myDisposable')
        expect(cleanup).not.toHaveBeenCalled()
        logic.unmount()
        expect(cleanup).toHaveBeenCalledTimes(1)
    })

    it('marks the manager as disposed and keeps cache.disposables reachable after unmount', () => {
        const logic = testDisposablesLogic()
        logic.mount()
        const manager = logic.cache.disposables
        logic.unmount()
        // The object must remain so that `cache.disposables.add(...)` does not null-deref
        // on deferred code paths (Mobile Safari race).
        expect(logic.cache.disposables).toBe(manager)
        expect(logic.cache.disposables.disposed).toBe(true)
    })

    it('makes cache.disposables.add a safe no-op after unmount', () => {
        const logic = testDisposablesLogic()
        logic.mount()
        const cache = logic.cache
        logic.unmount()

        const setup = jest.fn(() => jest.fn())
        // This is the exact race the bug report describes: a deferred callback
        // calling cache.disposables.add(...) after the logic unmounted.
        expect(() => cache.disposables.add(setup, 'late')).not.toThrow()
        // The setup must not run on a disposed manager.
        expect(setup).not.toHaveBeenCalled()
    })

    it('makes cache.disposables.dispose a safe no-op after unmount', () => {
        const logic = testDisposablesLogic()
        logic.mount()
        const cache = logic.cache
        logic.unmount()

        expect(() => cache.disposables.dispose('never-registered')).not.toThrow()
        expect(cache.disposables.dispose('never-registered')).toBe(false)
    })

    it('does not throw when a deferred setTimeout callback adds after unmount', async () => {
        jest.useFakeTimers()
        try {
            const logic = testDisposablesLogic()
            logic.mount()
            const cache = logic.cache

            // Schedule an add() that will fire after the logic unmounts.
            const deferredSetup = jest.fn(() => jest.fn())
            setTimeout(() => {
                cache.disposables.add(deferredSetup, 'deferred')
            }, 50)

            logic.unmount()

            // Fire the pending timer — this reproduces the "TypeError: null is not an
            // object (evaluating 'o.disposables.add')" reported on Mobile Safari.
            expect(() => jest.advanceTimersByTime(100)).not.toThrow()
            expect(deferredSetup).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
        }
    })

    it('gives a fresh manager when a logic re-mounts after unmount', () => {
        const logic = testDisposablesLogic()
        logic.mount()
        const firstManager = logic.cache.disposables
        logic.unmount()
        expect(firstManager.disposed).toBe(true)

        logic.mount()
        expect(logic.cache.disposables).not.toBe(firstManager)
        expect(logic.cache.disposables.disposed).toBe(false)
        logic.unmount()
    })
})
