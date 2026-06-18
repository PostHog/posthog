// Pure presentation helpers ported from desktop `@posthog/core/inbox/reportPresentation`.
// Shared across the Inbox cards/detail so the conventional-commit + headline parsing
// lives in exactly one place.

const MAX_HEADLINE_LENGTH = 140
const SENTENCE_END = /([.!?])[*_`]*(?=\s|$)/
const EDGE_EMPHASIS = /^[*_`\s]+|[*_`\s]+$/g
const CONVENTIONAL_COMMIT_TITLE = /^(\w+)(?:\(([^)]*)\))?!?:\s*(.+)$/

/** Compact single-sentence headline derived from a report summary, for list rendering. */
export function deriveHeadline(summary: string | null | undefined): string | null {
    if (typeof summary !== 'string') {
        return null
    }
    const trimmed = summary.trim()
    if (!trimmed) {
        return null
    }
    const firstLine = trimmed.split(/\r?\n/, 1)[0] ?? ''
    let headline = firstLine
    const sentenceMatch = SENTENCE_END.exec(firstLine)
    if (sentenceMatch) {
        headline = firstLine.slice(0, sentenceMatch.index + sentenceMatch[1].length)
    }
    headline = headline.replace(EDGE_EMPHASIS, '').trim()
    if (!headline) {
        return null
    }
    if (headline.length > MAX_HEADLINE_LENGTH) {
        headline = `${headline.slice(0, MAX_HEADLINE_LENGTH).trimEnd()}…`
    }
    return headline
}

export interface ParsedConventionalCommitTitle {
    type: string
    scope: string | null
    description: string
}

export function parseConventionalCommitTitle(title: string | null | undefined): ParsedConventionalCommitTitle | null {
    if (typeof title !== 'string') {
        return null
    }
    const trimmed = title.trim()
    if (!trimmed) {
        return null
    }
    const match = CONVENTIONAL_COMMIT_TITLE.exec(trimmed)
    if (!match) {
        return null
    }
    const description = match[3].trim()
    if (!description) {
        return null
    }
    return { type: match[1].toLowerCase(), scope: match[2]?.trim() || null, description }
}

export function displayConventionalCommitTitle(title: string | null | undefined, fallback: string): string {
    const parsed = parseConventionalCommitTitle(title)
    if (parsed) {
        return parsed.description
    }
    const trimmed = title?.trim()
    return trimmed ? trimmed : fallback
}

/**
 * Return the URL only if it's a safe `http(s)` link, otherwise `null`. Guards external `href`s
 * against `javascript:` / `data:` and other script-bearing schemes – `implementation_pr_url`
 * originates from an agent's raw task-run output and is not scheme-validated server-side.
 */
export function safeHttpUrl(url: string | null | undefined): string | null {
    if (!url) {
        return null
    }
    try {
        const { protocol } = new URL(url)
        return protocol === 'http:' || protocol === 'https:' ? url : null
    } catch {
        return null
    }
}

/** Canonical GitHub PR URL path matcher: `/<owner>/<repo>/pull/<number>`. */
const PR_URL_PATH = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:$|[/?#])/

export interface ParsedPrUrlParts {
    owner: string
    repo: string
    number: string
    repoSlug: string
}

/** Parse a canonical GitHub PR URL into its owner / repo / number / repoSlug parts. */
export function parsePrUrlParts(prUrl: string): ParsedPrUrlParts | null {
    try {
        const match = new URL(prUrl).pathname.match(PR_URL_PATH)
        if (!match) {
            return null
        }
        const [, owner, repo, number] = match
        return { owner, repo, number, repoSlug: `${owner}/${repo}` }
    } catch {
        return null
    }
}

/** Parse a GitHub PR URL into its repo slug, e.g. `posthog/posthog`. */
export function parsePrRepoSlug(prUrl: string): string | null {
    return parsePrUrlParts(prUrl)?.repoSlug ?? null
}
