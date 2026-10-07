import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'

import {
    buildAgentPrompt,
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

    const MCP_LINE = `If working with PostHog data would help with this task, use the PostHog MCP server in PostHog project 42. If the server is not connected, ask me to install it by running \`${MCP_INSTALL_COMMAND}\` in a terminal.`

    it.each([
        ['an external agent', 'cursor', false, 42, `Fix it\n\n${MCP_LINE}`],
        ['the clipboard', 'clipboard', false, 42, `Fix it\n\n${MCP_LINE}`],
        ['an unknown project', 'cursor', false, null, `Fix it\n\n${MCP_LINE.replace(' in PostHog project 42', '')}`],
        ['PostHog AI', 'posthog-ai', false, 42, 'Fix it\n'],
        ['raw content', 'cursor', true, 42, 'Fix it\n'],
    ] as const)('builds the prompt for %s', (_, agentKey, raw, projectId, expected) => {
        const action = { key: 'fix', label: 'Fix', buildPrompt: () => 'Fix it\n', raw }
        expect(buildAgentPrompt(action, agentKey, projectId)).toBe(expected)
    })

    it('does not split an emoji when it truncates a prompt at the cap', () => {
        expect(() => buildClaudeCodeDeepLink('a'.repeat(4_999) + '😀')).not.toThrow()
    })
})
