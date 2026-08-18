import { COMMON_REPLAYER_CONFIG, highSpeedAnimationStyleRules } from './index'

// posthog-js/* ships ESM that the test transform can't load directly; these values are
// only used by sibling plugins, not by the config object under test.
jest.mock('posthog-js/rrweb', () => ({
    Replayer: jest.fn(),
    canvasMutation: jest.fn(),
}))
jest.mock('posthog-js/rrweb-types', () => ({
    EventType: {},
    IncrementalSource: {},
}))

describe('COMMON_REPLAYER_CONFIG', () => {
    it('keeps the replay iframe scriptless by never enabling UNSAFE_replayCanvas', () => {
        // UNSAFE_replayCanvas makes rrweb add `allow-scripts` to the replay iframe sandbox.
        // Combined with the `allow-same-origin` rrweb requires, that pair lets untrusted
        // recorded content remove its own sandbox and run with full app-origin access.
        // PostHog renders canvas via CanvasReplayerPlugin instead, so this must stay off.
        expect(COMMON_REPLAYER_CONFIG.UNSAFE_replayCanvas).toBe(false)
    })

    describe('highSpeedAnimationStyleRules', () => {
        it.each([0.5, 1, 1.9])('adds no rule below the high-speed threshold (%p)', (speed) => {
            expect(highSpeedAnimationStyleRules(speed)).toEqual([])
        })

        it.each([2, 4, 8])('snaps animations to their end state at or above the threshold (%p)', (speed) => {
            const rules = highSpeedAnimationStyleRules(speed)
            expect(rules).toHaveLength(1)
            // `animation: none` froze content at its pre-animation state (e.g. opacity: 0), so the
            // rule must snap to the end state instead of suppressing animations outright.
            expect(rules[0]).not.toContain('animation: none')
            expect(rules[0]).toContain('animation-fill-mode: forwards')
        })
    })
})
