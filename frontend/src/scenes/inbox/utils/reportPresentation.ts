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

/** Parse a GitHub PR URL into its repo slug, e.g. `posthog/posthog`. */
export function parsePrRepoSlug(prUrl: string): string | null {
    try {
        const url = new URL(prUrl)
        const match = url.pathname.match(/^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:$|[/?#])/)
        if (!match) {
            return null
        }
        return `${match[1]}/${match[2]}`
    } catch {
        return null
    }
}
