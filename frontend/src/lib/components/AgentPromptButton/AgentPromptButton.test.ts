import {
    buildClaudeCodeDeepLink,
    buildClaudeCodeWebLink,
    buildClaudeDesktopDeepLink,
    buildCodexDeepLink,
    buildCursorDeepLink,
    buildPostHogCodeDeepLink,
} from './AgentPromptButton'

describe('AgentPromptButton', () => {
    it.each([
        [
            'PostHog Desktop with a repository',
            buildPostHogCodeDeepLink('fix this', 'posthog/posthog'),
            'posthog-code://new?prompt=fix%20this&repo=posthog%2Fposthog',
        ],
        [
            'PostHog Desktop without a repository',
            buildPostHogCodeDeepLink('fix this'),
            'posthog-code://new?prompt=fix%20this',
        ],
        [
            'Codex with a repository',
            buildCodexDeepLink('fix this', 'posthog/posthog'),
            'codex://new?prompt=fix%20this&originUrl=https%3A%2F%2Fgithub.com%2Fposthog%2Fposthog',
        ],
        ['Codex without a repository', buildCodexDeepLink('fix this'), 'codex://new?prompt=fix%20this'],
        ['Claude Desktop', buildClaudeDesktopDeepLink('fix this'), 'claude://code/new?q=fix%20this'],
        [
            'Claude Code on the web with a repository',
            buildClaudeCodeWebLink('fix this', 'posthog/posthog'),
            'https://claude.ai/code?prompt=fix%20this&repositories=posthog%2Fposthog',
        ],
    ])('builds a %s link', (_, link, expected) => {
        expect(link).toBe(expected)
    })

    it.each([
        ['Cursor', (prompt: string) => buildCursorDeepLink(prompt), 10_000],
        ['Claude Code on the web', (prompt: string) => buildClaudeCodeWebLink(prompt, 'posthog/posthog'), 8_000],
    ])('keeps the whole %s URL within its length cap when encoding inflates the prompt', (_, build, maxLength) => {
        const link = build('a b/c?'.repeat(5_000))
        expect(link.length).toBeLessThanOrEqual(maxLength)
        expect(link.length).toBeGreaterThan(maxLength - 30)
    })

    it('does not split an emoji when it truncates a prompt at the cap', () => {
        expect(() => buildClaudeCodeDeepLink('a'.repeat(4_999) + '😀')).not.toThrow()
    })
})
