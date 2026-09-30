import { useState } from 'react'
import { useActions, useValues } from 'kea'
import { withLimit } from './utils'
import { IconChevronDown, IconCopy, IconLogomark, IconSparkles } from '@posthog/icons'

const LIMIT_LONG = 8000
const LIMIT_CLAUDE = 5000
const LIMIT_SHORT = 4000

function openDeepLink(buildDeepLink: (prompt: string) => string): (prompt: string) => void {
    return (prompt: string) => window.open(buildDeepLink(prompt), '_blank')
}

export function buildPostHogCodeDeepLink(prompt: string, repository: string, customPrefix: string = 'posthog-code') {
    const repoParam = repository ? `&repo=${encodeURIComponent(repository)}` : ''
    return `${customPrefix}://new?prompt=${encodeURIComponent(prompt)}${repoParam}`
}

export function buildClaudeCodeDeepLink(prompt: string, repository: string) {
    const query = withLimit(prompt, LIMIT_CLAUDE, (text) => encodeURIComponent(text))
    const repoParam = repository ? `&repo=${encodeURIComponent(repository)}&` : ''
    return `claude-cli://open?${repoParam}q=${query}`
}

export function buildCursorDeepLink(prompt: string, repository: string) {
    return withLimit(
        prompt,
        LIMIT_LONG,
        (text) => `cursor://anysphere.cursor-deeplink/prompt?text=${encodeURIComponent(text)}`
    )
}

export function buildCodexDeepLink(prompt: string) {
    return withLimit(prompt, LIMIT_SHORT, (text) => `codex://new?prompt=${encodeURIComponent(text)}`)
}

const AGENTS: Record<string, any> = {
    'posthog-ai': {
        name: 'PostHog Desktop',
        logo: 'IconLogomark',
        className: 'size-4 shrink-0',
        verb: 'Open',
        open: (prompt: string, repository: string) => window.open(buildPostHogCodeDeepLink(prompt, repository), '_blank'),
    },
    'claude-code': {
        name: 'Claude Code',
        logo: 'ClaudeLogo',
        verb: 'Open',
        open: (prompt: string, repository: string) => window.open(buildClaudeCodeDeepLink(prompt, repository), '_blank'),
    },
    'cursor': {
        name: 'Cursor',
        logo: 'CursorLogo',
        verb: 'Open',
        open: (prompt: string, repository: string) => window.open(buildCursorDeepLink(prompt, repository), '_blank'),
    },
    'codex': {
        name: 'Codex',
        logo: 'OpenAiLogo',
        verb: 'Open',
        open: (prompt: string, repository: string) => window.open(buildCodexDeepLink(prompt), '_blank'),
    }
}
