import type { BuiltLogic } from 'kea'

import { disposablesPlugin } from './kea-disposables'

type FakeLogic = {
    cache: { disposables?: any; [key: string]: any }
    pathString: string
    isMounted: jest.Mock<boolean, []>
}

function createFakeLogic(pathString = 'test.kea-disposables'): FakeLogic {
    return {
        cache: {},
        pathString,
        isMounted: jest.fn(() => true),
    }
}

function afterMount(logic: FakeLogic): void {
    // The plugin's event signature is `(logic, plugin) => void`; we only need the logic.
    ;(disposablesPlugin.events!.afterMount as any)(logic as unknown as BuiltLogic)
}

function beforeUnmount(logic: FakeLogic): void {
    // Simulate kea's behavior where isMounted() becomes false on final unmount.
    logic.isMounted.mockReturnValue(false)
    ;(disposablesPlugin.events!.beforeUnmount as any)(logic as unknown as BuiltLogic)
}

describe('kea-disposables plugin', () => {
    it('exposes a manager on cache.disposables after mount', () => {
        const logic = createFakeLogic()
        afterMount(logic)
        expect(logic.cache.disposables).toBeTruthy()
        expect(typeof logic.cache.disposables.add).toBe('function')
        expect(typeof logic.cache.disposables.dispose).toBe('function')
        expect(logic.cache.disposables.disposed).toBe(false)
        beforeUnmount(logic)
    })

    it('runs registered cleanup on unmount', () => {
        const cleanup = jest.fn()
        const logic = createFakeLogic()
        afterMount(logic)
        logic.cache.disposables.add(() => cleanup, 'myDisposable')
        expect(cleanup).not.toHaveBeenCalled()
        beforeUnmount(logic)
        expect(cleanup).toHaveBeenCalledTimes(1)
    })

    it('marks the manager as disposed and keeps cache.disposables reachable after unmount', () => {
        const logic = createFakeLogic()
        afterMount(logic)
        const manager = logic.cache.disposables
        beforeUnmount(logic)
        // The object must remain so that `cache.disposables.add(...)` does not null-deref
        // on deferred code paths (Mobile Safari race).
        expect(logic.cache.disposables).toBe(manager)
        expect(logic.cache.disposables.disposed).toBe(true)
    })

    it('makes cache.disposables.add a safe no-op after unmount', () => {
        const logic = createFakeLogic()
        afterMount(logic)
        const cache = logic.cache
        beforeUnmount(logic)

        const setup = jest.fn(() => jest.fn())
        // This is the exact race the bug report describes: a deferred callback
        // calling cache.disposables.add(...) after the logic unmounted.
        expect(() => cache.disposables.add(setup, 'late')).not.toThrow()
        // The setup must not run on a disposed manager.
        expect(setup).not.toHaveBeenCalled()
    })

    it('makes cache.disposables.dispose a safe no-op after unmount', () => {
        const logic = createFakeLogic()
        afterMount(logic)
        const cache = logic.cache
        beforeUnmount(logic)

        expect(() => cache.disposables.dispose('never-registered')).not.toThrow()
        expect(cache.disposables.dispose('never-registered')).toBe(false)
    })

    it('does not throw when a deferred setTimeout callback adds after unmount', () => {
        jest.useFakeTimers()
        try {
            const logic = createFakeLogic()
            afterMount(logic)
            const cache = logic.cache

            // Schedule an add() that will fire after the logic unmounts.
            const deferredSetup = jest.fn(() => jest.fn())
            setTimeout(() => {
                cache.disposables.add(deferredSetup, 'deferred')
            }, 50)

            beforeUnmount(logic)

            // Fire the pending timer — this reproduces the "TypeError: null is not an
            // object (evaluating 'o.disposables.add')" reported on Mobile Safari.
            expect(() => jest.advanceTimersByTime(100)).not.toThrow()
            expect(deferredSetup).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
        }
    })

    it('replaces a disposed manager with a fresh one on re-mount', () => {
        const logic = createFakeLogic()
        afterMount(logic)
        const firstManager = logic.cache.disposables
        beforeUnmount(logic)
        expect(firstManager.disposed).toBe(true)

        // Kea would call isMounted() → true again on re-mount.
        logic.isMounted.mockReturnValue(true)
        afterMount(logic)
        expect(logic.cache.disposables).not.toBe(firstManager)
        expect(logic.cache.disposables.disposed).toBe(false)
        beforeUnmount(logic)
    })
})
