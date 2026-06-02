import type { LemonTagType } from '@posthog/lemon-ui'

import { identifierToHuman } from 'lib/utils'

import { categoryForKind, HEALTH_CATEGORY_CONFIG, KIND_LABELS } from './healthCategories'
import type { HealthIssueKind } from './healthCategories'
import type { HealthIssue, HealthIssueSeverity } from './types'
import { SEVERITY_ORDER } from './types'

export const severityToTagType = (severity: HealthIssueSeverity): LemonTagType => {
    switch (severity) {
        case 'critical':
            return 'danger'
        case 'warning':
            return 'warning'
        case 'info':
            return 'completion'
    }
}

export const severityLabel = (severity: HealthIssueSeverity): string => {
    return severity.charAt(0).toUpperCase() + severity.slice(1)
}

export const worstSeverity = (issues: HealthIssue[]): HealthIssueSeverity => {
    for (const severity of SEVERITY_ORDER) {
        if (issues.some((i) => i.severity === severity)) {
            return severity
        }
    }
    return 'info'
}

export const severityColor = (severity: HealthIssueSeverity): string => {
    switch (severity) {
        case 'critical':
            return 'text-danger'
        case 'warning':
            return 'text-warning'
        case 'info':
            return 'text-muted'
    }
}

export const kindToLabel = (kind: string): string => {
    if (kind in KIND_LABELS) {
        return KIND_LABELS[kind as HealthIssueKind]
    }
    return kind
        .split('_')
        .map((word, i) => (i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
        .join(' ')
}

// Helpers below build the prompts that the "Ask PostHog AI" entry points send to the AI side panel.
// PostHog AI receives a snapshot of the issue(s) embedded in the prompt — it does not re-run the checks.

const truncate = (value: string, max: number): string => (value.length > max ? `${value.slice(0, max)}…` : value)

const categoryLabel = (kind: string): string => HEALTH_CATEGORY_CONFIG[categoryForKind(kind)].label

const formatPayloadValue = (value: unknown): string | null => {
    if (value === null || value === undefined) {
        return null
    }
    if (Array.isArray(value)) {
        const items = value.filter((v) => typeof v === 'string' || typeof v === 'number')
        return items.length > 0 ? items.join(', ') : null
    }
    if (typeof value === 'object') {
        return null
    }
    return truncate(String(value), 500)
}

const issueDetailLines = (issue: HealthIssue): string[] => {
    const payload = issue.payload ?? {}
    const lines: string[] = []
    for (const [key, value] of Object.entries(payload)) {
        const formatted = formatPayloadValue(value)
        if (formatted) {
            lines.push(`${identifierToHuman(key)}: ${formatted}`)
        }
    }
    return lines
}

const issueSummaryLine = (issue: HealthIssue): string => {
    const category = categoryLabel(issue.kind)
    const reason = issue.payload?.reason ? ` — ${truncate(String(issue.payload.reason), 200)}` : ''
    return `- [${severityLabel(issue.severity)}] ${kindToLabel(issue.kind)} (${category})${reason}`
}

const sortedBySeverity = (issues: HealthIssue[]): HealthIssue[] =>
    [...issues].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity))

/** Preset questions surfaced as a dropdown next to the overview-level "Ask PostHog AI" button. */
export const HEALTH_OVERVIEW_QUESTIONS = [
    "What's wrong with my project's health?",
    'Which health issues should I fix first?',
    'How do I fix these health issues?',
] as const

const DEFAULT_OVERVIEW_QUESTION = "What's wrong with my project's health, and how do I fix it?"

/** Build the prompt for asking PostHog AI about a single health issue. */
export const buildHealthIssuePrompt = (issue: HealthIssue): string => {
    const category = categoryLabel(issue.kind)
    const lines = [
        'I need help with a health issue in my PostHog project.',
        '',
        `Issue: ${kindToLabel(issue.kind)}`,
        `Severity: ${severityLabel(issue.severity)}`,
        `Category: ${category}`,
    ]
    const details = issueDetailLines(issue)
    if (details.length > 0) {
        lines.push('Details:', ...details.map((detail) => `- ${detail}`))
    }
    lines.push('', 'Please explain what this means, the likely cause, and the concrete steps to fix it.')
    return lines.join('\n')
}

/** Build the prompt for asking PostHog AI about every active issue on the Health overview. */
export const buildHealthOverviewPrompt = (
    issues: HealthIssue[],
    question: string = DEFAULT_OVERVIEW_QUESTION
): string => {
    if (issues.length === 0) {
        return (
            'The Health overview for my PostHog project currently shows no active health issues. ' +
            'What should I monitor to keep my project healthy, and how can I confirm my data is being ingested correctly?'
        )
    }
    const count = issues.length
    const issuesClause = count === 1 ? 'is the 1 active health issue' : `are the ${count} active health issues`
    return [
        question,
        '',
        `Here ${issuesClause} on my PostHog Health overview:`,
        ...sortedBySeverity(issues).map(issueSummaryLine),
        '',
        'Please explain what is going wrong, which issues to prioritize, and the concrete steps to fix each one.',
    ].join('\n')
}
