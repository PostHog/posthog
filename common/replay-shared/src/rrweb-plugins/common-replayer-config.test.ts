/**
 * @jest-environment jsdom
 */
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

    describe('extension popup rule', () => {
        const parseShippedRule = (): CSSStyleRule => {
            const css = COMMON_REPLAYER_CONFIG.insertStyleRules?.find((rule) => rule.includes('translate-tooltip-mtz'))
            const style = document.createElement('style')
            style.textContent = css ?? ''
            document.head.appendChild(style)
            const rules = [...(style.sheet?.cssRules ?? [])]
            expect(rules).toHaveLength(1)
            return rules[0] as CSSStyleRule
        }

        it('hides what it matches', () => {
            expect(parseShippedRule().style.display).toBe('none')
        })

        it.each([
            ['div', 'translate-tooltip-mtz blue sm-root translate hidden_translate', true],
            ['span', 'translate-button-mtz hidden_translate blue', true],
            ['div', 'app-content', false],
        ])('page-level %s.%s hidden: %s', (tagName, className, expected) => {
            const el = document.createElement(tagName)
            el.className = className
            document.body.appendChild(el)
            expect(el.matches(parseShippedRule().selectorText)).toBe(expected)
        })

        it('leaves an identically named element inside the recorded page alone', () => {
            // Matching below <body> could hide a customer's own content and blank the replay.
            const app = document.createElement('div')
            const nested = document.createElement('div')
            nested.className = 'translate-tooltip-mtz'
            app.appendChild(nested)
            document.body.appendChild(app)
            expect(nested.matches(parseShippedRule().selectorText)).toBe(false)
        })
    })
})
