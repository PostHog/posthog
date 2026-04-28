import { actions, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'

import { initKeaTests } from '~/test/init'

import type { testLogicType, observableLogicType, remountLogicType } from './postUnmountCleanupPlugin.testType'

// Regression test for the `postUnmountCleanupPlugin` registered in `initKea.ts`.
//
// Pins the contract that the QA review highlighted:
// - `logic.events`, `logic.listeners`, and `logic.connections` are all cleared
//   on the next macrotask (not synchronously) so kea's `unmountLogic` sweep
//   and synchronous `mount()/unmount()/mount()` test patterns aren't broken.
// - `isMounted()` lives in the BuiltLogic's closure rather than a data field
//   and continues to work post-unmount.
// - `beforeUnmount` handlers (and any other lifecycle event kea fires inside
//   the unmount call stack) see populated state.
//
// This test exists so that whoever simplifies the plugin once kea ships an
// upstream null-safe iteration in `unmountLogic` can prove the guarantees
// still hold.

describe('postUnmountCleanupPlugin', () => {
    beforeEach(() => {
        initKeaTests()
    })

    function makeTestLogic(): ReturnType<typeof testLogic.build> {
        return testLogic.build()
    }

    const testLogic = kea<testLogicType>([
        path(['__tests__', 'postUnmountCleanupPluginTestLogic']),
        actions({ ping: true }),
        reducers({ count: [0, { ping: (state: number) => state + 1 }] }),
        selectors({ doubled: [(s) => [s.count], (count: number) => count * 2] }),
        listeners(() => ({ ping: () => undefined })),
        beforeUnmount(() => undefined),
    ])

    it('clears logic.events, .listeners, and .connections on the next macrotask after final unmount', async () => {
        const logic = makeTestLogic()
        const unmount = logic.mount()

        expect(Object.keys(logic.events).length).toBeGreaterThan(0)
        expect(Object.keys(logic.listeners).length).toBeGreaterThan(0)
        expect(Object.keys(logic.connections).length).toBeGreaterThan(0)

        unmount()

        // Cleanup is deferred so kea's own unmount sweep and any synchronous
        // remount can run against a populated graph.
        expect(Object.keys(logic.events).length).toBeGreaterThan(0)
        expect(Object.keys(logic.listeners).length).toBeGreaterThan(0)
        expect(Object.keys(logic.connections).length).toBeGreaterThan(0)

        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(logic.events).toEqual({})
        expect(logic.listeners).toEqual({})
        expect(logic.connections).toEqual({})
    })

    it('keeps logic.isMounted() working after the plugin clears fields', async () => {
        const logic = makeTestLogic()
        const unmount = logic.mount()

        expect(logic.isMounted()).toBe(true)

        unmount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        // `isMounted()` lives in the closure returned by kea's builder, not
        // in a field we clear. After unmount it just answers "no".
        expect(typeof logic.isMounted).toBe('function')
        expect(logic.isMounted()).toBe(false)
    })

    it('lets beforeUnmount handlers see populated logic state', () => {
        let snapshotInBeforeUnmount: { events: number; listeners: number } | null = null

        const observableLogic = kea<observableLogicType>([
            path(['__tests__', 'postUnmountCleanupPluginObservableLogic']),
            actions({ tick: true }),
            reducers({ ticks: [0, { tick: (state: number) => state + 1 }] }),
            listeners(() => ({ tick: () => undefined })),
            (logic) => {
                beforeUnmount(() => {
                    snapshotInBeforeUnmount = {
                        events: Object.keys(logic.events).length,
                        listeners: Object.keys(logic.listeners).length,
                    }
                })(logic)
            },
        ])

        const unmount = observableLogic.build().mount()
        unmount()

        expect(snapshotInBeforeUnmount).not.toBeNull()
        expect(snapshotInBeforeUnmount!.events).toBeGreaterThan(0)
        expect(snapshotInBeforeUnmount!.listeners).toBeGreaterThan(0)
    })

    it('does not break mount() -> unmount() -> mount() on the same captured BuiltLogic reference', () => {
        // This is the pattern in `saveToDatasetButtonLogic.test.ts:476-489`.
        // After unmount, the test re-mounts the SAME BuiltLogic instance.
        // `mountLogic` walks `Object.keys(logic.connections)` — if our
        // plugin cleared connections synchronously, this sweep would mount
        // nothing on the second `mount()`.
        const remountLogic = kea<remountLogicType>([
            path(['__tests__', 'postUnmountCleanupPluginRemountLogic']),
            actions({ go: true }),
            reducers({ went: [0, { go: (state: number) => state + 1 }] }),
        ])

        const built = remountLogic.build()
        const firstUnmount = built.mount()
        firstUnmount()

        const secondUnmount = built.mount()
        expect(built.isMounted()).toBe(true)
        secondUnmount()
    })
})
