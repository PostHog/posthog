import { dayjs } from 'lib/dayjs'
import { scoutDisplayName } from 'lib/signals/signalCardSourceLine'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

export type TodayReportIcon =
    | 'pr'
    | 'replay'
    | 'error'
    | 'llm'
    | 'support'
    | 'survey'
    | 'analytics'
    | 'logs'
    | 'alert'
    | 'scout'
    | 'github'
    | 'gitlab'
    | 'linear'
    | 'jira'
    | 'database'
    | 'signal'
    | 'code'
    | 'slack'

export interface TodayReportSource {
    label: string
    color: string
    icon: TodayReportIcon
}

const SOURCES: Record<string, TodayReportSource> = {
    error_tracking: { label: 'Error tracking', color: 'var(--color-product-error-tracking-light)', icon: 'error' },
    sentry: { label: 'Sentry', color: 'var(--color-product-error-tracking-light)', icon: 'error' },
    session_replay: { label: 'Session replay', color: 'var(--color-product-session-replay-light)', icon: 'replay' },
    replay_vision: { label: 'Replay vision', color: 'var(--color-product-session-replay-light)', icon: 'replay' },
    llm_analytics: { label: 'LLM analytics', color: 'var(--color-product-llm-analytics-light)', icon: 'llm' },
    analytics: { label: 'Product analytics', color: 'var(--color-product-product-analytics-light)', icon: 'analytics' },
    conversations: { label: 'Support', color: 'var(--color-product-support-light)', icon: 'support' },
    zendesk: { label: 'Zendesk', color: 'var(--color-product-support-light)', icon: 'support' },
    surveys: { label: 'Surveys', color: 'var(--color-product-surveys-light)', icon: 'survey' },
    logs: { label: 'Logs', color: 'var(--color-product-logs-light)', icon: 'logs' },
    github: { label: 'GitHub', color: 'var(--color-text-secondary)', icon: 'github' },
    gitlab: { label: 'GitLab', color: 'var(--color-text-secondary)', icon: 'gitlab' },
    linear: { label: 'Linear', color: 'var(--color-text-secondary)', icon: 'linear' },
    jira: { label: 'Jira', color: 'var(--color-text-secondary)', icon: 'jira' },
    signals_scout: { label: 'Scout', color: 'var(--color-text-secondary)', icon: 'scout' },
    pganalyze: { label: 'pganalyze', color: 'var(--color-text-secondary)', icon: 'database' },
    // Today item sources that are not signal products.
    product_analytics: {
        label: 'Product analytics',
        color: 'var(--color-product-product-analytics-light)',
        icon: 'analytics',
    },
    alerts: { label: 'Alerts', color: 'var(--color-product-product-analytics-light)', icon: 'alert' },
    support: { label: 'Support', color: 'var(--color-product-support-light)', icon: 'support' },
}

const FALLBACK_SOURCE: TodayReportSource = {
    label: 'Signals',
    color: 'var(--color-text-secondary)',
    icon: 'signal',
}

export function reportTitle(report: Pick<SignalReport, 'title'>): string {
    return capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))
}

export function sourceLabel(source: string): string {
    return SOURCES[source]?.label ?? source.replace(/_/g, ' ').replace(/^./, (first) => first.toUpperCase())
}

export function sourceStyle(source: string | null | undefined): TodayReportSource {
    if (!source) {
        return FALLBACK_SOURCE
    }
    return SOURCES[source] ?? { ...FALLBACK_SOURCE, label: sourceLabel(source) }
}

/** The style of the product that contributed the report's first signal. */
function reportSource(report: Pick<SignalReport, 'source_products'>): TodayReportSource {
    return sourceStyle(report.source_products?.[0])
}

export function reportMeta(report: Pick<SignalReport, 'source_products' | 'updated_at'>): string {
    return `${reportSource(report).label} · ${dayjs(report.updated_at).fromNow()}`
}

export function lowerFirst(text: string): string {
    // Keep acronyms such as "API" or "LLM" as they are.
    return /^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text
}

const SHOWN_SOURCES = 2
const SOURCE_LINE_CHARS = 32

const PROPER_WORDS: Record<string, string> = {
    ai: 'AI',
    api: 'API',
    github: 'GitHub',
    llm: 'LLM',
    mcp: 'MCP',
    posthog: 'PostHog',
    pr: 'PR',
    sql: 'SQL',
    ui: 'UI',
    ux: 'UX',
}

export function scoutLabel(skillName: string | null | undefined): string | null {
    const name = scoutDisplayName(skillName)
    if (!name) {
        return null
    }
    const words = name.split(' ').map((word) => PROPER_WORDS[word.toLowerCase()] ?? word)
    return `${words.join(' ').replace(/\b(self) (driving)\b/i, '$1-$2')} scout`
}

export function reportSourceLine(report: Pick<SignalReport, 'source_products' | 'scout_name'>): {
    line: string
    title: string
} {
    const scout = scoutLabel(report.scout_name)
    const labels = [
        ...new Set(
            (report.source_products ?? []).map((source) =>
                source === 'signals_scout' ? (scout ?? 'Scout') : sourceStyle(source).label
            )
        ),
    ]
    if (labels.length === 0) {
        return { line: scout ?? sourceStyle(null).label, title: '' }
    }
    const count = labels.slice(0, SHOWN_SOURCES).join(', ').length > SOURCE_LINE_CHARS ? 1 : SHOWN_SOURCES
    const shown = labels.slice(0, count).join(', ')
    const rest = labels.length - count
    return { line: rest > 0 ? `${shown} +${rest}` : shown, title: labels.join(', ') }
}
