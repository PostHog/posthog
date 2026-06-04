import { COMMON_REPLAYER_CONFIG } from './index'

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
})
