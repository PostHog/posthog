import { actions, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'

import { initKeaTests } from '~/test/init'

import type { testLogicType, observableLogicType } from './postUnmountCleanupPlugin.testType'

// Regression test for the `postUnmountCleanupPlugin` registered in `initKea.ts`.
//
// Pins the contract that the QA review highlighted: the plugin clears
// `logic.events` and `logic.listeners` synchronously after final unmount,
// and `logic.connections` on the next macrotask. `isMounted()` continues
// to work because it lives in the BuiltLogic's closure rather than a data
// field. This test exists so that whoever simplifies the plugin once kea
// ships an upstream null-safe iteration in `unmountLogic` can prove the
// guarantees still hold.

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

    it('synchronously clears logic.events and logic.listeners on final unmount', () => {
        const logic = makeTestLogic()
        const unmount = logic.mount()

        expect(Object.keys(logic.events).length).toBeGreaterThan(0)
        expect(Object.keys(logic.listeners).length).toBeGreaterThan(0)

        unmount()

        expect(logic.events).toEqual({})
        expect(logic.listeners).toEqual({})
    })

    it('clears logic.connections on the next macrotask', async () => {
        const logic = makeTestLogic()
        const unmount = logic.mount()

        // Self-reference plus any plugin-injected connections.
        expect(Object.keys(logic.connections).length).toBeGreaterThan(0)

        unmount()

        // Connections survive the synchronous clear so kea's `unmountLogic`
        // can finish iterating its `pathStrings` loop without crashing.
        expect(Object.keys(logic.connections).length).toBeGreaterThan(0)

        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(logic.connections).toEqual({})
    })

    it('keeps logic.isMounted() working after the plugin clears fields', () => {
        const logic = makeTestLogic()
        const unmount = logic.mount()

        expect(logic.isMounted()).toBe(true)

        unmount()

        // `isMounted()` lives in the closure returned by kea's builder, not
        // in a field we clear. After unmount it just answers "no".
        expect(typeof logic.isMounted).toBe('function')
        expect(logic.isMounted()).toBe(false)
    })

    it('lets beforeUnmount handlers see populated logic state before the clear', () => {
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

        // beforeUnmount fires before our postUnmountCleanup afterUnmount, so it
        // observes the populated graph.
        expect(snapshotInBeforeUnmount).not.toBeNull()
        expect(snapshotInBeforeUnmount!.events).toBeGreaterThan(0)
        expect(snapshotInBeforeUnmount!.listeners).toBeGreaterThan(0)
    })
})
