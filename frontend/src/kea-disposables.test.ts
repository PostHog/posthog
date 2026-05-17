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

interface DisposableTestLogicType {
    actionCreators: any
    selectors: any
    values: any
    actions: any
    cache: any
    mount: () => () => void
    unmount: () => void
}

describe('disposablesPlugin', () => {
    let logic: DisposableTestLogicType
    let setupCalls: number
    let cleanupCalls: number

    beforeEach(() => {
        initKeaTests()
        setupCalls = 0
        cleanupCalls = 0
        setHidden(false)

        logic = kea<logicType>([path(['test', 'disposablesPluginTest'])]) as unknown as DisposableTestLogicType
        logic.mount()
    })

    afterEach(() => {
        try {
            logic.unmount()
        } catch {}
        setHidden(false)
    })

    const makeSetup = () => () => {
        setupCalls += 1
        return () => {
            cleanupCalls += 1
        }
    }

    it('runs setup immediately when added while page is visible', () => {
        setHidden(false)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(1)
        expect(cleanupCalls).toBe(0)
    })

    it('does NOT run setup when add() is called while page is hidden (default pauseOnPageHidden=true)', () => {
        setHidden(true)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(0)
        // entry should still be registered so resume can run it later
        expect(logic.cache.disposables.registry.has('k1')).toBe(true)
    })

    it('runs setup on next visibility-visible for paused-at-birth entries', () => {
        setHidden(true)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(0)

        setHidden(false)
        expect(setupCalls).toBe(1)
    })

    it('runs setup immediately when add() called with pauseOnPageHidden=false even if hidden', () => {
        setHidden(true)
        logic.cache.disposables.add(makeSetup(), 'k1', { pauseOnPageHidden: false })
        expect(setupCalls).toBe(1)
    })

    it('runs cleanup on visibility-hidden for default disposables', () => {
        setHidden(false)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(1)
        expect(cleanupCalls).toBe(0)

        setHidden(true)
        expect(cleanupCalls).toBe(1)
    })

    it('does NOT run cleanup on visibility-hidden for opted-out disposables', () => {
        setHidden(false)
        logic.cache.disposables.add(makeSetup(), 'k1', { pauseOnPageHidden: false })
        setHidden(true)
        expect(cleanupCalls).toBe(0)
    })

    it('replacing a keyed disposable cleans up the previous one', () => {
        setHidden(false)
        logic.cache.disposables.add(makeSetup(), 'k1')
        logic.cache.disposables.add(makeSetup(), 'k1')
        // first setup ran, first cleanup ran (because replaced), second setup ran
        expect(setupCalls).toBe(2)
        expect(cleanupCalls).toBe(1)
    })

    it('replacing a keyed disposable while hidden cleans up the previous and stores paused', () => {
        setHidden(false)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(1)

        setHidden(true)
        // visibility-hidden runs cleanup for the active entry
        expect(cleanupCalls).toBe(1)

        // replace while hidden — should not run setup
        logic.cache.disposables.add(makeSetup(), 'k1')
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
        logic.cache.disposables.add(makeSetup(), 'pollTimeout')
        expect(setupCalls).toBe(1)

        setHidden(true)
        expect(cleanupCalls).toBe(1)

        // Simulate fetch returning and `finally` re-scheduling the timer
        logic.cache.disposables.add(makeSetup(), 'pollTimeout')
        // CRITICAL: setup must NOT run while hidden — that was the bug
        expect(setupCalls).toBe(1)

        // When the user returns to the tab, the timer should be set up
        setHidden(false)
        expect(setupCalls).toBe(2)
    })

    it('dispose() runs cleanup and removes the entry', () => {
        setHidden(false)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(1)

        logic.cache.disposables.dispose('k1')
        expect(cleanupCalls).toBe(1)
        expect(logic.cache.disposables.registry.has('k1')).toBe(false)

        // Subsequent visibility changes should not affect anything
        setHidden(true)
        setHidden(false)
        expect(setupCalls).toBe(1)
        expect(cleanupCalls).toBe(1)
    })

    it('dispose() on a paused-at-birth entry runs no-op cleanup and removes it', () => {
        setHidden(true)
        logic.cache.disposables.add(makeSetup(), 'k1')
        expect(setupCalls).toBe(0)

        // Setup never ran, so disposing should not run any user cleanup
        logic.cache.disposables.dispose('k1')
        expect(cleanupCalls).toBe(0)
        expect(logic.cache.disposables.registry.has('k1')).toBe(false)
    })
})
