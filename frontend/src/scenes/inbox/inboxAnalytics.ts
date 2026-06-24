import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'

import { SignalReport, SignalReportActionability, SignalReportPriority } from './types'

/**
 * Inbox telemetry. Mirrors the desktop "Code" app's inbox analytics (event names + property
 * shapes from `packages/shared/src/analytics-events.ts`) so the two clients are comparable in
 * one PostHog project. Every event carries `inbox_client` so funnels and breakdowns can split
 * cloud from desktop — cloud sends `'cloud'`, the desktop app sends `'desktop'`.
 */
export const INBOX_CLIENT = 'cloud' as const

export const INBOX_EVENTS = {
    VIEWED: 'Inbox viewed',
    REPORT_OPENED: 'Inbox report opened',
    REPORT_CLOSED: 'Inbox report closed',
    REPORT_ACTION: 'Inbox report action',
    REPORT_FEEDBACK: 'Inbox report feedback',
    SOURCE_CONNECTED: 'Signal source connected',
    SOURCE_INTEREST: 'signals source interest',
} as const

type InboxEvent = (typeof INBOX_EVENTS)[keyof typeof INBOX_EVENTS]

/** Action surface an `Inbox report action` fired from. */
export type InboxReportActionSurface = 'detail_pane' | 'list_row' | 'bulk_bar'

/** How a report detail was opened. */
export type InboxReportOpenMethod = 'click' | 'deeplink' | 'unknown'

/** How a report detail was closed. */
export type InboxReportCloseMethod = 'next_report' | 'deselected' | 'unmount'

/** Sentiment captured by the report feedback button. */
export type InboxReportFeedbackSentiment = 'positive' | 'negative'

/**
 * Report actions cloud actually emits. Names match the desktop enum one-for-one (so the
 * `action_type` breakdown reads the same across clients), plus a cloud-only `restore` for the
 * Archive tab. Desktop-only variants we don't fire yet are intentionally omitted.
 */
export type InboxReportActionType =
    | 'dismiss'
    | 'restore'
    | 'create_pr'
    | 'add_suggested_reviewer'
    | 'remove_suggested_reviewer'

function captureInboxEvent(event: InboxEvent, properties: Record<string, unknown>): void {
    posthog.capture(event, { inbox_client: INBOX_CLIENT, ...properties })
}

/** Whole hours since the report was created, rounded to one decimal. Mirrors desktop `report_age_hours`. */
function reportAgeHours(report: Pick<SignalReport, 'created_at'>): number {
    if (!report.created_at) {
        return 0
    }
    const hours = dayjs().diff(dayjs(report.created_at), 'hour', true)
    return Math.max(0, Math.round(hours * 10) / 10)
}

interface BaseReportProperties {
    report_id: string
    report_age_hours: number
    priority: SignalReportPriority | null
    actionability: SignalReportActionability | null
}

/**
 * Identity + classification for a report. Kept to opaque ids, enums, ages, and counts — it never
 * includes the agent-generated report title, which can echo proprietary detail from a customer's
 * own data. User-authored notes (a dismissal reason note, feedback note) are a different case: they
 * are the actionable signal we want, so the relevant capture calls attach them explicitly.
 */
function baseReportProperties(report: SignalReport): BaseReportProperties {
    return {
        report_id: report.id,
        report_age_hours: reportAgeHours(report),
        priority: report.priority ?? null,
        actionability: report.actionability ?? null,
    }
}

/** Per-priority counts of the visible reports (P0–P4, plus unknown). Mirrors desktop's breakdown. */
function priorityBreakdown(reports: SignalReport[]): Record<string, number> {
    const counts = { p0: 0, p1: 0, p2: 0, p3: 0, p4: 0, unknown: 0 }
    for (const report of reports) {
        const key = report.priority ? (report.priority.toLowerCase() as 'p0' | 'p1' | 'p2' | 'p3' | 'p4') : 'unknown'
        counts[key] += 1
    }
    return {
        priority_p0_count: counts.p0,
        priority_p1_count: counts.p1,
        priority_p2_count: counts.p2,
        priority_p3_count: counts.p3,
        priority_p4_count: counts.p4,
        priority_unknown_count: counts.unknown,
    }
}

/** Per-actionability counts of the visible reports. Mirrors desktop's breakdown. */
function actionabilityBreakdown(reports: SignalReport[]): Record<string, number> {
    const counts = { immediately_actionable: 0, requires_human_input: 0, not_actionable: 0, unknown: 0 }
    for (const report of reports) {
        const key = report.actionability ?? 'unknown'
        counts[key] += 1
    }
    return {
        actionability_immediately_actionable_count: counts.immediately_actionable,
        actionability_requires_human_input_count: counts.requires_human_input,
        actionability_not_actionable_count: counts.not_actionable,
        actionability_unknown_count: counts.unknown,
    }
}

export function captureInboxViewed(params: {
    tab: string
    reports: SignalReport[]
    totalCount: number
    hasActiveFilters: boolean
    sourceProductFilter: string[]
    priorityFilter: string[]
    scope: string
}): void {
    captureInboxEvent(INBOX_EVENTS.VIEWED, {
        tab: params.tab,
        report_count: params.reports.length,
        total_count: params.totalCount,
        is_empty: params.totalCount === 0,
        has_active_filters: params.hasActiveFilters,
        source_product_filter: params.sourceProductFilter,
        priority_filter: params.priorityFilter,
        scope: params.scope,
        ...priorityBreakdown(params.reports),
        ...actionabilityBreakdown(params.reports),
    })
}

export function captureInboxReportOpened(params: {
    report: SignalReport
    openMethod: InboxReportOpenMethod
    previousReportId: string | null
    rank: number | null
    listSize: number | null
}): void {
    captureInboxEvent(INBOX_EVENTS.REPORT_OPENED, {
        ...baseReportProperties(params.report),
        status: params.report.status ?? null,
        source_products: params.report.source_products ?? [],
        open_method: params.openMethod,
        previous_report_id: params.previousReportId,
        rank: params.rank,
        list_size: params.listSize,
    })
}

export function captureInboxReportClosed(params: {
    report: SignalReport
    timeSpentMs: number
    closeMethod: InboxReportCloseMethod
}): void {
    captureInboxEvent(INBOX_EVENTS.REPORT_CLOSED, {
        ...baseReportProperties(params.report),
        time_spent_ms: params.timeSpentMs,
        close_method: params.closeMethod,
    })
}

export function captureInboxReportAction(params: {
    /** Omitted for bulk actions, which act on a selection rather than a single report. */
    report?: SignalReport | null
    actionType: InboxReportActionType
    surface: InboxReportActionSurface
    isBulk?: boolean
    bulkSize?: number
    extra?: Record<string, unknown>
}): void {
    const base = params.report
        ? baseReportProperties(params.report)
        : { report_id: null, report_age_hours: 0, priority: null, actionability: null }
    captureInboxEvent(INBOX_EVENTS.REPORT_ACTION, {
        ...base,
        action_type: params.actionType,
        surface: params.surface,
        is_bulk: params.isBulk ?? false,
        bulk_size: params.bulkSize ?? 1,
        ...params.extra,
    })
}

/**
 * Free-form feedback on a single report, fired from the detail pane's feedback button. Unlike a
 * dismiss, this is feedback-only: the report stays in the inbox. Carries the thumbs sentiment plus
 * the optional note text so we can read what people actually think of a report (and its PR).
 */
export function captureInboxReportFeedback(params: {
    report: SignalReport
    sentiment: InboxReportFeedbackSentiment
    note: string
    surface: InboxReportActionSurface
}): void {
    captureInboxEvent(INBOX_EVENTS.REPORT_FEEDBACK, {
        ...baseReportProperties(params.report),
        sentiment: params.sentiment,
        has_pr: !!params.report.implementation_pr_url,
        ...(params.note ? { note: params.note } : {}),
        surface: params.surface,
    })
}

export function captureSignalSourceConnected(params: {
    sourceProduct: string
    sourceType: string
    isFirstConnection: boolean
    viaSetupWizard: boolean
}): void {
    captureInboxEvent(INBOX_EVENTS.SOURCE_CONNECTED, {
        source_product: params.sourceProduct,
        source_type: params.sourceType,
        is_first_connection: params.isFirstConnection,
        via_setup_wizard: params.viaSetupWizard,
    })
}

export function captureSignalSourceInterest(source: string): void {
    captureInboxEvent(INBOX_EVENTS.SOURCE_INTEREST, { source })
}
