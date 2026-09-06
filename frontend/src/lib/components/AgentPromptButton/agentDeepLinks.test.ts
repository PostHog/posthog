import {
    buildClaudeCodeDeepLink,
    buildCodexDeepLink,
    buildCursorDeepLink,
    buildPostHogCodeDeepLink,
} from './agentDeepLinks'

describe('agentDeepLinks', () => {
    it.each([
        ['with a repository', 'posthog/posthog', 'posthog-code://new?prompt=fix%20this&repo=posthog%2Fposthog'],
        ['without a repository', undefined, 'posthog-code://new?prompt=fix%20this'],
    ])('builds a PostHog Desktop deep link %s', (_, repository, expected) => {
        expect(buildPostHogCodeDeepLink('fix this', repository)).toBe(expected)
    })

    it('double-encodes the Cursor prompt so reserved characters survive Cursor decoding the link', () => {
        expect(buildCursorDeepLink('fix a&b')).toBe('cursor://anysphere.cursor-deeplink/prompt?text=fix%2520a%2526b')
    })

    // Agents that reject an over-long deep link get a truncated prompt instead of a dropped one.
    it.each([
        ['Claude Code', buildClaudeCodeDeepLink, 5_000],
        ['Codex', buildCodexDeepLink, 4_000],
        ['Cursor', buildCursorDeepLink, 8_000],
    ])('truncates the %s prompt', (_, buildUrl, limit) => {
        const url = buildUrl('x'.repeat(limit * 2))
        expect(url).toContain('x'.repeat(limit))
        expect(url).not.toContain('x'.repeat(limit + 1))
    })
})
