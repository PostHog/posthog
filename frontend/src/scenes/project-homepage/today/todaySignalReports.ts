import { dayjs } from 'lib/dayjs'

import type { TodayReportCard } from '~/layout/today/todayPreviewCards'

import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

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

/** One run of text in the briefing. A run with `reportId` links to that report. */
export interface TodayBriefingSegment {
    text: string
    reportId?: string
    /** Marks the report that already has a pull request waiting for review. */
    highlight?: boolean
}

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

/** Questions that only ask for an answer, so they are safe to offer on any report. */
export const GENERAL_REPORT_PROMPTS = [
    'Why is this happening?',
    'Who is affected, and how badly?',
    'What would you look at first?',
]

export function reportTitle(report: Pick<SignalReport, 'title'>): string {
    return report.title?.trim() || 'Untitled report'
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
export function reportSource(report: Pick<SignalReport, 'source_products'>): TodayReportSource {
    return sourceStyle(report.source_products?.[0])
}

/** The hover card of one of the team's reports, shown while the personal briefing is not written yet. */
export function teamReportCard(report: SignalReport): TodayReportCard {
    return {
        key: `team-report:${report.id}`,
        reportId: report.id,
        title: reportTitle(report),
        reason: null,
        stateLabel: null,
        resolved: false,
        priority: report.priority ?? null,
        summary: report.summary_lead || null,
        pullRequestState: report.implementation_pr_merged ? 'merged' : (report.implementation_pr_state ?? null),
        pullRequestUrl: report.implementation_pr_url ?? null,
        signalCount: report.signal_count,
        updatedAt: report.updated_at,
        metrics: report.metrics ?? [],
        charts: report.charts ?? [],
        sourceLabel: reportSource(report).label,
    }
}

export function reportIcon(report: Pick<SignalReport, 'source_products' | 'implementation_pr_url'>): TodayReportIcon {
    return report.implementation_pr_url ? 'pr' : reportSource(report).icon
}

export function reportMeta(report: Pick<SignalReport, 'source_products' | 'updated_at'>): string {
    return `${reportSource(report).label} · ${dayjs(report.updated_at).fromNow()}`
}

/**
 * The prompts offered under a report. The report's own suggestions can ask for action, so they are
 * offered only where the Inbox offers them too. Every other report gets questions that only ask for
 * an answer.
 */
export function reportPrompts(report: SignalReport): string[] {
    const suggested = isActionCapableReport(report) ? (report.suggested_prompts ?? []) : []
    return suggested.length ? suggested : GENERAL_REPORT_PROMPTS
}

function lowerFirst(text: string): string {
    // Keep acronyms such as "API" or "LLM" as they are.
    return /^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text
}

/** One linked sentence per report, so every report in the briefing opens from the text. */
export function briefingForReports(reports: SignalReport[]): TodayBriefingSegment[][] {
    const [first, ...rest] = reports
    if (!first) {
        return []
    }
    const paragraphs: TodayBriefingSegment[][] = [
        [{ text: reportTitle(first), reportId: first.id, highlight: !!first.implementation_pr_url }, { text: '.' }],
    ]
    if (rest.length) {
        paragraphs.push([
            { text: 'Also on your list: ' },
            ...rest.flatMap((report, index): TodayBriefingSegment[] => [
                { text: lowerFirst(reportTitle(report)), reportId: report.id },
                { text: index === rest.length - 1 ? '.' : index === rest.length - 2 ? ', and ' : ', ' },
            ]),
        ])
    }
    return paragraphs
}
