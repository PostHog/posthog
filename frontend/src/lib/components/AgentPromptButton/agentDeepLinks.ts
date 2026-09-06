/**
 * Deep links that hand a prompt to a coding agent. Shared by the app's `AgentPromptButton`
 * and the toolbar's field notes menu, which cannot import that component because it pulls in
 * quill, Radix, and the Max logic.
 */

export interface AgentDeepLinkOptions {
    /** GitHub `owner/repo` slug for agents that can open a specific repository. */
    repository?: string
}

export interface AgentDeepLinkTarget {
    key: string
    name: string
    buildUrl: (prompt: string, options?: AgentDeepLinkOptions) => string
}

// A deep link travels as a URL, so each agent takes only as much prompt as it accepts.
const LIMIT_LONG = 8_000
const LIMIT_CLAUDE = 5_000
const LIMIT_SHORT = 4_000

export function buildPostHogCodeDeepLink(prompt: string, repository?: string): string {
    const repoParam = repository ? `&repo=${encodeURIComponent(repository)}` : ''
    return `posthog-code://new?prompt=${encodeURIComponent(prompt)}${repoParam}`
}

export function buildClaudeCodeDeepLink(prompt: string, repository?: string): string {
    const repoParam = repository ? `repo=${encodeURIComponent(repository)}&` : ''
    return `claude-cli://open?${repoParam}q=${encodeURIComponent(prompt.slice(0, LIMIT_CLAUDE))}`
}

export function buildCursorDeepLink(prompt: string): string {
    // Cursor decodes the full deep link before it parses the query params, so reserved
    // characters need a second layer of escaping to survive that first decode.
    return `cursor://anysphere.cursor-deeplink/prompt?text=${encodeURIComponent(
        encodeURIComponent(prompt.slice(0, LIMIT_LONG))
    )}`
}

export function buildCodexDeepLink(prompt: string): string {
    return `codex://new?prompt=${encodeURIComponent(prompt.slice(0, LIMIT_SHORT))}`
}

export const AGENT_DEEP_LINK_TARGETS: AgentDeepLinkTarget[] = [
    {
        key: 'posthog-code',
        name: 'PostHog Desktop',
        buildUrl: (prompt, options) => buildPostHogCodeDeepLink(prompt, options?.repository),
    },
    {
        key: 'claude-code',
        name: 'Claude Code',
        buildUrl: (prompt, options) => buildClaudeCodeDeepLink(prompt, options?.repository),
    },
    { key: 'cursor', name: 'Cursor', buildUrl: (prompt) => buildCursorDeepLink(prompt) },
    { key: 'codex', name: 'Codex', buildUrl: (prompt) => buildCodexDeepLink(prompt) },
]
