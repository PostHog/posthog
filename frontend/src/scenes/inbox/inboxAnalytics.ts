import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'

import { SignalReport, SignalReportActionability, SignalReportPriority, SignalRunKind } from './types'

/**
 * Inbox telemetry. Mirrors the desktop "Code" app's inbox analytics (event names + property
 * shapes from `packages/shared/src/analytics-events.ts`) so the two clients are comparable in
 * one PostHog project. Every event carries `inbox_client` so funnels and breakdowns can split
 * cloud from desktop — cloud sends `'cloud'`, the desktop app sends `'desktop'`.
 */
export const INBOX_CLIENT = 'cloud' as const

export const INBOX_EVENTS = {
    VIEWED: 'Inbox viewed',
    PANEL_VIEWED: 'Inbox panel viewed',
    QUERY_CHANGED: 'Inbox query changed',
    REPORTS_IMPRESSED: 'Inbox reports impressed',
    REPORT_OPENED: 'Inbox report opened',
    REPORT_CLOSED: 'Inbox report closed',
    REPORT_ACTION: 'Inbox report action',
    REPORT_ACTION_COMPLETED: 'Inbox report action completed',
    REPORT_FEEDBACK: 'Inbox report feedback',
    REPORT_FEEDBACK_NOTE: 'Inbox report feedback note',
    SETTINGS_CHANGED: 'Inbox settings changed',
    SOURCE_CONNECTED: 'Signal source connected',
    SOURCE_DISABLED: 'Signal source disabled',
    SOURCE_INTEREST: 'signals source interest',
    // Scout-troop management. Names and property shapes match the desktop app one-for-one so both
    // clients union in one project; desktop sends no `inbox_client`, so its rows read as null.
    SCOUT_FLEET_VIEWED: 'Scout fleet viewed',
    SCOUT_DETAIL_VIEWED: 'Scout detail viewed',
    SCOUT_CONFIG_CHANGED: 'Scout config changed',
    SCOUT_ACTION: 'Scout action',
    SCOUT_CHAT_STARTED: 'Scout chat started',
    RUN_OPENED: 'Inbox run opened',
} as const

type InboxEvent = (typeof INBOX_EVENTS)[keyof typeof INBOX_EVENTS]

/** Action surface an `Inbox report action` fired from. */
export type InboxReportActionSurface = 'detail_pane' | 'detail_footer' | 'list_row' | 'bulk_bar'

/** How a report detail was opened. */
export type InboxReportOpenMethod = 'click' | 'deeplink' | 'unknown'

/** How a report detail was closed. */
export type InboxReportCloseMethod = 'next_report' | 'deselected' | 'unmount'

/** Sentiment captured by the report feedback thumbs. */
export type InboxReportFeedbackSentiment = 'positive' | 'negative'

/**
 * Report actions cloud actually emits. Names match the desktop enum one-for-one (so the
 * `action_type` breakdown reads the same across clients), plus cloud-only `restore` (Archive tab),
 * `view_diff`, and the section expand/collapse pair (desktop splits those per section instead).
 * Desktop-only variants we don't fire yet are intentionally omitted.
 */
export type InboxReportActionType =
    | 'dismiss'
    | 'discuss'
    | 'restore'
    | 'create_pr'
    | 'refund'
    | 'open_pr'
    | 'view_diff'
    | 'expand_section'
    | 'collapse_section'
    | 'add_suggested_reviewer'
    | 'remove_suggested_reviewer'

/**
 * Whether a task-kickoff action (`discuss` / `create_pr`) actually produced a task. The press itself
 * is already an {@link captureInboxReportAction} event; without the outcome the two are
 * indistinguishable, so an attempted PR counts the same as a created one.
 */
export type InboxReportActionOutcome = 'success' | 'failure' | 'blocked'

/** Panels that replace the report list and so never fire `Inbox viewed`. */
export type InboxPanelName = 'runs' | 'config' | 'scratchpad' | 'findings'

/** Which control moved the report list to a new query. `url` is a shared/deep link being applied. */
export type InboxQueryChange = 'scope' | 'sort' | 'source_product' | 'scout' | 'priority' | 'search' | 'clear' | 'url'

/** Surface a scout-management event fired from. Matches the desktop values. */
export type ScoutSurface = 'fleet_list' | 'scout_detail' | 'empty_state'

/**
 * Scout-management actions. The first block matches desktop's enum; the trailing three are
 * cloud-only, covering affordances desktop doesn't have (creating and deleting scouts, and the
 * scratchpad callout).
 */
export type ScoutActionType =
    | 'open_settings'
    | 'close_settings'
    | 'open_skill_in_posthog'
    | 'open_helper_skill'
    | 'open_findings'
    | 'toggle_hide_disabled'
    | 'expand_run'
    | 'collapse_run'
    | 'filter_runs'
    | 'expand_emission'
    | 'collapse_emission'
    | 'copy_finding_link'
    | 'open_task_run'
    | 'open_linked_report'
    | 'create_scout'
    | 'delete_scout'
    | 'open_memory'

/** What a scout chat CTA was asking for. Matches the desktop values. */
export type ScoutChatType = 'author_scout' | 'fleet_overview' | 'recent_signals'

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

/**
 * Impression log for the report list: which reports were shown, at what rank, with the
 * classification each carried at render time. This is the negative class (and position record)
 * for ranking-model training — `Inbox report opened` alone only records the clicked report.
 * Fired with the newly-shown reports each time the visible list grows (first page, pagination,
 * refresh), never twice for the same report within a tab mount.
 */
export function captureInboxReportsImpressed(params: {
    tab: string
    /** Only the newly-impressed reports, in list order. */
    reports: SignalReport[]
    /** 1-based rank of each impressed report in the full loaded list, parallel to `reports`. */
    ranks: number[]
    listSize: number
    totalCount: number | null
    hasActiveFilters: boolean
    scope: string
}): void {
    captureInboxEvent(INBOX_EVENTS.REPORTS_IMPRESSED, {
        tab: params.tab,
        list_size: params.listSize,
        total_count: params.totalCount,
        has_active_filters: params.hasActiveFilters,
        scope: params.scope,
        impression_count: params.reports.length,
        impressions: params.reports.map((report, index) => ({
            ...baseReportProperties(report),
            rank: params.ranks[index],
            status: report.status ?? null,
            source_products: report.source_products ?? [],
            signal_count: report.signal_count,
            total_weight: report.total_weight,
            is_suggested_reviewer: report.is_suggested_reviewer,
        })),
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
 * Feedback on a single report, fired from the thumbs at the end of the report body. Unlike a
 * dismiss, this is feedback-only: the report stays in the inbox. The sentiment is the label the
 * ranking work trains against, so it carries the same report classification as the impression and
 * open events. `note` is optional — the thumbs submit on one click, with no note.
 */
export function captureInboxReportFeedback(params: {
    report: SignalReport
    sentiment: InboxReportFeedbackSentiment
    note?: string
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

/**
 * Optional free-text note, offered only once a rating is already recorded. It rides on its own
 * event rather than re-firing {@link captureInboxReportFeedback} so sentiment stays exactly one
 * event per rating; join back to the rating on `report_id`. Carries `sentiment` too so a note can
 * be read without that join.
 */
export function captureInboxReportFeedbackNote(params: {
    report: SignalReport
    sentiment: InboxReportFeedbackSentiment
    note: string
    surface: InboxReportActionSurface
}): void {
    captureInboxEvent(INBOX_EVENTS.REPORT_FEEDBACK_NOTE, {
        ...baseReportProperties(params.report),
        sentiment: params.sentiment,
        has_pr: !!params.report.implementation_pr_url,
        note: params.note,
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

/**
 * A source switched off. Its own event rather than an `enabled` flag on
 * {@link captureSignalSourceConnected}, so existing connection counts keep meaning connections —
 * turning a source off is the shape of churn, not a negative connection.
 */
export function captureSignalSourceDisabled(params: { sourceProduct: string; sourceType: string }): void {
    captureInboxEvent(INBOX_EVENTS.SOURCE_DISABLED, {
        source_product: params.sourceProduct,
        source_type: params.sourceType,
    })
}

export function captureSignalSourceInterest(source: string): void {
    captureInboxEvent(INBOX_EVENTS.SOURCE_INTEREST, { source })
}

/**
 * Outcome of a task-kickoff action, fired once the request settles. Pairs with the press event on
 * `report_id` + `action_type`. `blocked` means we never issued the request (no AI consent), which is
 * a product problem rather than a failure — hence its own bucket.
 */
export function captureInboxReportActionCompleted(params: {
    report: SignalReport
    actionType: InboxReportActionType
    outcome: InboxReportActionOutcome
    /** Only set for `blocked`, and only ever our own consent copy — never a server error body. */
    blockedReason?: string | null
}): void {
    captureInboxEvent(INBOX_EVENTS.REPORT_ACTION_COMPLETED, {
        ...baseReportProperties(params.report),
        action_type: params.actionType,
        outcome: params.outcome,
        ...(params.blockedReason ? { blocked_reason: params.blockedReason } : {}),
    })
}

/**
 * A surface that replaces the report list (Runs, Configuration, and the two scout panels). None of
 * them render `InboxReportList`, so without this they're invisible — `Inbox viewed` only ever fires
 * for the flat report tabs.
 */
export function captureInboxPanelViewed(params: { panel: InboxPanelName; itemCount?: number | null }): void {
    captureInboxEvent(INBOX_EVENTS.PANEL_VIEWED, {
        panel: params.panel,
        item_count: params.itemCount ?? null,
    })
}

/**
 * The list moved to a new query — a filter, sort, search, or scope change. `Inbox viewed` fires once
 * per tab mount, so re-querying an already-open inbox left no trace at all: a user working a filtered
 * list all day and one who arrived and sat still looked identical.
 *
 * The search *term* is deliberately not sent (only its length): unlike a dismissal reason, it's
 * incidental typing that can name a customer's own entities. `change` says which control moved; the
 * remaining properties are the resulting query, so any single event describes the full view.
 */
export function captureInboxQueryChanged(params: {
    change: InboxQueryChange
    tab: string | null
    scope: string
    sortField: string
    sortDirection: string
    sourceProductFilter: string[]
    scoutFilter: string[]
    priorityFilter: string[]
    searchQuery: string
    hasActiveFilters: boolean
}): void {
    const search = params.searchQuery.trim()
    captureInboxEvent(INBOX_EVENTS.QUERY_CHANGED, {
        change: params.change,
        tab: params.tab,
        scope: params.scope,
        sort_field: params.sortField,
        sort_direction: params.sortDirection,
        source_product_filter: params.sourceProductFilter,
        scout_filter: params.scoutFilter,
        priority_filter: params.priorityFilter,
        has_search: search.length > 0,
        search_length: search.length,
        has_active_filters: params.hasActiveFilters,
    })
}

/**
 * A team-level inbox setting was changed (self-driving autostart, Slack notifications, base-branch
 * overrides). Fired once the request settles, so `success` distinguishes a saved change from a
 * rejected one. `old_value` isn't carried: the patch is applied optimistically before the listener
 * runs, so the prior value is no longer readable there — the previous event for the same `setting`
 * is the transition.
 */
export function captureInboxSettingsChanged(params: {
    setting: string
    newValue: unknown
    success: boolean
    /** Whether the setting governs the whole team or just the person changing it. */
    scope: 'team' | 'user'
}): void {
    captureInboxEvent(INBOX_EVENTS.SETTINGS_CHANGED, {
        setting: params.setting,
        ...settingValueProperties('new_value', params.newValue),
        success: params.success,
        setting_scope: params.scope,
    })
}

/**
 * A setting's value, safe to ship. Scalars go as-is; a structured value is reduced to how many
 * entries it holds, because those carry the customer's own names — the base-branch overrides are a
 * map of their repositories, a Slack destination names their channel.
 */
function settingValueProperties(key: string, value: unknown): Record<string, unknown> {
    if (typeof value === 'object' && value !== null) {
        return { [key]: null, [`${key}_size`]: Object.keys(value).length }
    }
    return { [key]: value ?? null, [`${key}_size`]: null }
}

/** Roster shape at the moment the scout troop list was opened. Mirrors desktop's `Scout fleet viewed`. */
export function captureScoutFleetViewed(params: {
    scoutCount: number
    enabledCount: number
    customCount: number
    dryRunCount: number
}): void {
    captureInboxEvent(INBOX_EVENTS.SCOUT_FLEET_VIEWED, {
        scout_count: params.scoutCount,
        enabled_count: params.enabledCount,
        custom_count: params.customCount,
        dry_run_count: params.dryRunCount,
        is_empty: params.scoutCount === 0,
    })
}

/** One scout's detail page opened, with its config and recent-window run shape. */
export function captureScoutDetailViewed(params: {
    skillName: string
    scoutOrigin: string | null
    enabled: boolean
    emit: boolean
    runIntervalMinutes: number | null
    runCount: number
    failedRunCount: number
    emittedSignalCount: number
}): void {
    captureInboxEvent(INBOX_EVENTS.SCOUT_DETAIL_VIEWED, {
        skill_name: params.skillName,
        scout_origin: params.scoutOrigin,
        enabled: params.enabled,
        emit: params.emit,
        has_config: true,
        run_interval_minutes: params.runIntervalMinutes,
        run_count: params.runCount,
        failed_run_count: params.failedRunCount,
        emitted_signal_count: params.emittedSignalCount,
    })
}

/**
 * One scout setting saved. Fired per changed field — a schedule switch patches two fields at once,
 * and rolling them into one event would make the `setting` breakdown lie about which control moved.
 */
export function captureScoutConfigChanged(params: {
    skillName: string
    scoutOrigin: string | null
    setting: string
    oldValue: unknown
    newValue: unknown
    success: boolean
}): void {
    captureInboxEvent(INBOX_EVENTS.SCOUT_CONFIG_CHANGED, {
        skill_name: params.skillName,
        scout_origin: params.scoutOrigin,
        setting: params.setting,
        ...settingValueProperties('old_value', params.oldValue),
        ...settingValueProperties('new_value', params.newValue),
        success: params.success,
    })
}

/** Any non-config interaction on the scout surfaces — expanding a run, copying a link, opening a skill. */
export function captureScoutAction(params: {
    actionType: ScoutActionType
    surface: ScoutSurface
    skillName?: string | null
    extra?: Record<string, unknown>
}): void {
    captureInboxEvent(INBOX_EVENTS.SCOUT_ACTION, {
        action_type: params.actionType,
        surface: params.surface,
        skill_name: params.skillName ?? null,
        ...params.extra,
    })
}

/**
 * A Runs tab row was opened. Nothing was captured here before, so a run that lands on a dead or
 * unrelated task page left no trace outside a session recording.
 */
export function captureInboxRunOpened(params: {
    kind: SignalRunKind
    status: string | null
    hasReport: boolean
}): void {
    captureInboxEvent(INBOX_EVENTS.RUN_OPENED, {
        run_kind: params.kind,
        run_status: params.status,
        has_report: params.hasReport,
    })
}

/** A scout CTA kicked off a cloud task ("Suggest a scout", the fleet-overview chips). */
export function captureScoutChatStarted(params: {
    chatType: ScoutChatType
    surface: ScoutSurface
    skillName?: string | null
}): void {
    captureInboxEvent(INBOX_EVENTS.SCOUT_CHAT_STARTED, {
        chat_type: params.chatType,
        surface: params.surface,
        skill_name: params.skillName ?? null,
    })
}
