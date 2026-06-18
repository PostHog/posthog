import { kea, path } from 'kea'

import { initKeaTests } from '~/test/init'

import type { logicType } from './kea-disposables.testType'

// Helper: trigger visibilitychange after mutating document.hidden
const setHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (hidden ? 'hidden' : 'visible'),
    })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('disposablesPlugin', () => {
    let logic: ReturnType<typeof kea<logicType>>
    let setupCalls: number
    let cleanupCalls: number

    beforeEach(() => {
        initKeaTests()
        setupCalls = 0
        cleanupCalls = 0
        setHidden(false)

        logic = kea<logicType>([path(['test', 'disposablesPluginTest'])])
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        setHidden(false)
    })

    const makeSetup = () => () => {
        setupCalls += 1
        return () => {
            cleanupCalls += 1
        }
    }

    describe.each<{
        label: string
        initialHidden: boolean
        options?: { pauseOnPageHidden?: boolean }
        expectedSetupCalls: number
        expectedRegistryHas: boolean
    }>([
        {
            label: 'visible, default options — runs setup immediately',
            initialHidden: false,
            expectedSetupCalls: 1,
            expectedRegistryHas: true,
        },
        {
            label: 'hidden, default options — defers setup, entry still registered',
            initialHidden: true,
            expectedSetupCalls: 0,
            expectedRegistryHas: true,
        },
        {
            label: 'hidden, pauseOnPageHidden=false — runs setup anyway',
            initialHidden: true,
            options: { pauseOnPageHidden: false },
            expectedSetupCalls: 1,
            expectedRegistryHas: true,
        },
    ])('add() — $label', ({ initialHidden, options, expectedSetupCalls, expectedRegistryHas }) => {
        it('matches expected setup/registry state', () => {
            setHidden(initialHidden)
            ;(logic as any).cache.disposables.add(makeSetup(), 'k1', options)
            expect(setupCalls).toBe(expectedSetupCalls)
            expect(cleanupCalls).toBe(0)
            expect((logic as any).cache.disposables.registry.has('k1')).toBe(expectedRegistryHas)
        })
    })

    it('runs setup on next visibility-visible for paused-at-birth entries', () => {
        setHidden(true)
        ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(0)

        setHidden(false)
        expect(setupCalls).toBe(1)
    })

    describe.each<{
        label: string
        options?: { pauseOnPageHidden?: boolean }
        expectedCleanupCalls: number
    }>([
        {
            label: 'default — cleanup runs on hide',
            expectedCleanupCalls: 1,
        },
        {
            label: 'pauseOnPageHidden=false — cleanup does NOT run on hide',
            options: { pauseOnPageHidden: false },
            expectedCleanupCalls: 0,
        },
    ])('visibility-hidden cleanup — $label', ({ options, expectedCleanupCalls }) => {
        it('matches expected cleanup count', () => {
            setHidden(false)
            ;(logic as any).cache.disposables.add(makeSetup(), 'k1', options)
            expect(setupCalls).toBe(1)
            setHidden(true)
            expect(cleanupCalls).toBe(expectedCleanupCalls)
        })
    })

    it('replacing a keyed disposable cleans up the previous one', () => {
        setHidden(false)
        ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
        ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
        // first setup ran, first cleanup ran (because replaced), second setup ran
        expect(setupCalls).toBe(2)
        expect(cleanupCalls).toBe(1)
    })

    it('replacing a keyed disposable while hidden cleans up the previous and stores paused', () => {
        setHidden(false)
        ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(1)

        setHidden(true)
        // visibility-hidden runs cleanup for the active entry
        expect(cleanupCalls).toBe(1)

        // replace while hidden — should not run setup
        ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(1) // unchanged
        // Plugin defensively re-runs the previous cleanup when replacing a key.
        // User-supplied cleanups must therefore be idempotent (clearTimeout on
        // an already-cleared id is fine). cleanupCalls bumps to 2 even though
        // the timer was already cleared on hide.
        expect(cleanupCalls).toBe(2)

        // Resume runs setup for the replaced entry
        setHidden(false)
        expect(setupCalls).toBe(2)
    })

    it('regression: re-adding a disposable while hidden (poll-rescheduling pattern) does not start a live timer', () => {
        // Simulates the bug: a fetch's `finally` block calls add('pollTimeout', ...)
        // while the page is hidden. Before the fix, this would create a live timer.
        // After the fix, the setup is deferred to next visibility-visible.
        setHidden(false)
        ;(logic as any).cache.disposables.add(makeSetup(), 'pollTimeout')
        expect(setupCalls).toBe(1)

        setHidden(true)
        expect(cleanupCalls).toBe(1)

        // Simulate fetch returning and `finally` re-scheduling the timer
        ;(logic as any).cache.disposables.add(makeSetup(), 'pollTimeout')
        // CRITICAL: setup must NOT run while hidden — that was the bug
        expect(setupCalls).toBe(1)

        // When the user returns to the tab, the timer should be set up
        setHidden(false)
        expect(setupCalls).toBe(2)
    })

    describe.each<{
        label: string
        initialHidden: boolean
        expectedSetupCalls: number
        expectedCleanupCalls: number
    }>([
        {
            label: 'active entry — cleanup runs',
            initialHidden: false,
            expectedSetupCalls: 1,
            expectedCleanupCalls: 1,
        },
        {
            label: 'paused-at-birth entry — no user cleanup runs',
            initialHidden: true,
            expectedSetupCalls: 0,
            expectedCleanupCalls: 0,
        },
    ])('dispose() — $label', ({ initialHidden, expectedSetupCalls, expectedCleanupCalls }) => {
        it('removes entry and runs cleanup as expected', () => {
            setHidden(initialHidden)
            ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
            expect(setupCalls).toBe(expectedSetupCalls)
            ;(logic as any).cache.disposables.dispose('k1')
            expect(cleanupCalls).toBe(expectedCleanupCalls)
            expect((logic as any).cache.disposables.registry.has('k1')).toBe(false)

            // Subsequent visibility changes should not affect anything
            setHidden(!initialHidden)
            setHidden(initialHidden)
            expect(setupCalls).toBe(expectedSetupCalls)
            expect(cleanupCalls).toBe(expectedCleanupCalls)
        })
    })

    it('logic.unmount() disposes all registered disposables (no leak when consumer omits beforeUnmount)', () => {
        // Pins the contract that supportTicketCounterLogic relies on after
        // dropping its explicit `beforeUnmount(() => disposables.disposeAll())`.
        setHidden(false)
        ;(logic as any).cache.disposables.add(makeSetup(), 'k1')
        ;(logic as any).cache.disposables.add(makeSetup(), 'k2')
        expect(setupCalls).toBe(2)
        expect(cleanupCalls).toBe(0)

        logic.unmount()
        expect(cleanupCalls).toBe(2)
    })
})
