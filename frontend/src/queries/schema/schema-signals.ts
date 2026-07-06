// Signal taxonomy types - shared contract between emitters and consumers

// ── Source taxonomy enums ───────────────────────────────────────────────────────

export enum SignalSourceProduct {
    SESSION_REPLAY = 'session_replay',
    LLM_ANALYTICS = 'llm_analytics',
    GITHUB = 'github',
    LINEAR = 'linear',
    ZENDESK = 'zendesk',
    CONVERSATIONS = 'conversations',
    ERROR_TRACKING = 'error_tracking',
    ENDPOINTS = 'endpoints',
    PGANALYZE = 'pganalyze',
    SIGNALS_SCOUT = 'signals_scout',
    LOGS = 'logs',
    HEALTH_CHECKS = 'health_checks',
    REPLAY_VISION = 'replay_vision',
}

export enum SignalSourceType {
    SESSION_ANALYSIS_CLUSTER = 'session_analysis_cluster',
    SESSION_PROBLEM = 'session_problem',
    EVALUATION = 'evaluation',
    EVALUATION_REPORT = 'evaluation_report',
    ISSUE = 'issue',
    TICKET = 'ticket',
    ISSUE_CREATED = 'issue_created',
    ISSUE_REOPENED = 'issue_reopened',
    ISSUE_SPIKING = 'issue_spiking',
    ENDPOINT_EXECUTION_FAILED = 'endpoint_execution_failed',
    ENDPOINT_BREAKDOWN_LIMIT_EXCEEDED = 'endpoint_breakdown_limit_exceeded',
    CROSS_SOURCE_ISSUE = 'cross_source_issue',
    ALERT_STATE_CHANGE = 'alert_state_change',
    HEALTH_ISSUE = 'health_issue',
    SCANNER_FINDING = 'scanner_finding',
}

// ── Shared optional remediation ──────────────────────────────────────────────────
// A known fix attached to a signal. Optional and separate from `extra`: `extra` is product-specific
// evidence; `remediation` is the fix guidance. Mirrors the health-checks `Remediation(human, agent)`
// constant so a check's remediation maps straight onto a signal. When present, the signal is treated
// as actionable: the research agent follows the `agent` guidance rather than investigating from
// scratch — it still runs, produces findings, and writes the human-facing report. Every variant may
// carry it.

export interface SignalRemediation {
    /** Human-facing fix steps (PostHog UI / alert destinations). Surfaced in the report for the reader. */
    human: string
    /** Agent-facing guidance: how to investigate (which MCP tools to call) and, where the fix lives
     *  in the user's codebase, how to apply it. The research agent treats this as authoritative — it
     *  still investigates and produces findings, but follows this instead of starting cold. */
    agent: string
    /** Suggested report priority; advisory, the research agent may override. */
    priority?: 'P0' | 'P1' | 'P2' | 'P3' | 'P4'
}

// ── Shared signal extra & input base ───────────────────────────────────────────────
// Marker base every per-source `extra` payload extends. Empty today: it gives the input base a
// single `extra` type to reference and is where any future cross-source extra field would live.
export interface SignalExtraBase {}

// Top-level fields every variant carries. Concrete variants narrow `source_type`, `source_product`,
// and `extra` to their specific literal/payload types (those narrowings discriminate the union).
// `remediation` is source-agnostic: any signal may carry it, even though only some sources emit it today.
export interface SignalInputBase {
    source_type: string
    source_product: string
    source_id: string
    description: string
    weight: number
    extra: SignalExtraBase
    remediation?: SignalRemediation
}

// ── Per-product signal extras & inputs ──────────────────────────────────────────

// Session replay problem (emitted per-session for problem-indicating segments)

export interface SessionProblemEventEntry {
    event: string
    timestamp: string
    current_url?: string
    event_type?: string
    interaction_text?: string
}

export interface SessionProblemSignalExtra extends SignalExtraBase {
    session_id: string
    segment_title: string
    start_time: string
    end_time: string
    problem_type: 'confusion' | 'abandonment' | 'blocking_exception' | 'non_blocking_exception' | 'failure'
    distinct_id: string
    session_start_time?: string
    session_end_time?: string
    session_duration?: number
    session_active_seconds?: number
    exported_asset_id?: number
    event_history?: SessionProblemEventEntry[]
}

export interface SessionProblemSignalInput extends SignalInputBase {
    source_type: 'session_problem'
    source_product: 'session_replay'
    extra: SessionProblemSignalExtra
}

/** @deprecated No longer emitted. */
export interface SessionReplaySegment {
    session_id: string
    start_time: string
    end_time: string
    distinct_id: string
    content: string
}

/** @deprecated No longer emitted. */
export interface SessionSegmentClusterMetrics {
    relevant_user_count: number
    active_users_in_period: number
    occurrence_count: number
}

/** @deprecated No longer emitted. */
export interface SessionSegmentClusterSignalExtra extends SignalExtraBase {
    label_title: string
    actionable: boolean
    segments: SessionReplaySegment[]
    metrics: SessionSegmentClusterMetrics
}

/** @deprecated No longer emitted. */
export interface SessionSegmentClusterSignalInput {
    source_type: 'session_segment_cluster'
    source_product: 'session_replay'
    source_id: string
    description: string
    weight: number
    extra: SessionSegmentClusterSignalExtra
}

// LLM evaluation

export interface LlmEvalSignalExtra extends SignalExtraBase {
    evaluation_id: string
    target_event_id?: string
    target_event_type?: string
    trace_id: string
    model?: string
    provider?: string
}

export interface LlmEvaluationSignalInput extends SignalInputBase {
    source_type: 'evaluation'
    source_product: 'llm_analytics'
    extra: LlmEvalSignalExtra
}

// LLM evaluation report (one signal per report run, distilled from many results)

export interface LlmEvalReportSignalExtra extends SignalExtraBase {
    evaluation_id: string
    evaluation_name: string
    evaluation_description: string
    report_id: string
    report_run_id: string
    period_start: string
    period_end: string
}

export interface LlmEvaluationReportSignalInput extends SignalInputBase {
    source_type: 'evaluation_report'
    source_product: 'llm_analytics'
    extra: LlmEvalReportSignalExtra
}

// Zendesk ticket

export interface ZendeskTicketSignalExtra extends SignalExtraBase {
    url: string
    type: string | null
    tags: string[]
    created_at: string
    priority: string | null
    status: string
}

export interface ZendeskTicketSignalInput extends SignalInputBase {
    source_type: 'ticket'
    source_product: 'zendesk'
    extra: ZendeskTicketSignalExtra
}

// GitHub issue

export interface GithubIssueSignalExtra extends SignalExtraBase {
    html_url: string
    number: number
    labels: string[]
    created_at: string
    updated_at: string
    locked: boolean
    state: string
}

export interface GithubIssueSignalInput extends SignalInputBase {
    source_type: 'issue'
    source_product: 'github'
    extra: GithubIssueSignalExtra
}

// Linear issue

export interface LinearIssueSignalExtra extends SignalExtraBase {
    url: string
    identifier: string
    number: number
    priority: number
    priority_label: string
    labels: string[]
    state_name: string | null
    state_type: string | null
    team_name: string | null
    created_at: string
    updated_at: string
}

export interface LinearIssueSignalInput extends SignalInputBase {
    source_type: 'issue'
    source_product: 'linear'
    extra: LinearIssueSignalExtra
}

// Conversations ticket

export interface ConversationsTicketSignalExtra extends SignalExtraBase {
    ticket_number: number
    channel_source: string
    channel_detail: string | null
    status: string
    priority: string | null
    created_at: string
    email_subject: string | null
}

export interface ConversationsTicketSignalInput extends SignalInputBase {
    source_type: 'ticket'
    source_product: 'conversations'
    extra: ConversationsTicketSignalExtra
}

// Error tracking

export interface ErrorTrackingSignalExtra extends SignalExtraBase {
    fingerprint: string
}

export interface ErrorTrackingSignalInput extends SignalInputBase {
    source_type: 'issue_created' | 'issue_reopened' | 'issue_spiking'
    source_product: 'error_tracking'
    extra: ErrorTrackingSignalExtra
}

// pganalyze issue (database performance finding)

export interface PgAnalyzeIssueReference {
    kind: string | null
    name: string | null
    url: string | null
    queryText: string | null
}

export interface PgAnalyzeIssueSignalExtra extends SignalExtraBase {
    severity: string | null
    references: PgAnalyzeIssueReference[]
    database_id: string | null
    server_human_id: string | null
    server_name: string | null
    synced_at: string
}

export interface PgAnalyzeIssueSignalInput extends SignalInputBase {
    source_type: 'issue'
    source_product: 'pganalyze'
    extra: PgAnalyzeIssueSignalExtra
}

// Endpoint execution failure

export interface EndpointExecutionFailedSignalExtra extends SignalExtraBase {
    endpoint_name: string
    endpoint_version: number | null
    materialized: boolean
    saved_query_id: string | null
    error_class: string
    error_message: string
}

export interface EndpointExecutionFailedSignalInput extends SignalInputBase {
    source_type: 'endpoint_execution_failed'
    source_product: 'endpoints'
    extra: EndpointExecutionFailedSignalExtra
}

// Endpoint breakdown limit exceeded — the 'Other' bucket appeared in results

export interface EndpointBreakdownLimitExceededSignalExtra extends SignalExtraBase {
    endpoint_name: string
    breakdown_limit: number
}

export interface EndpointBreakdownLimitExceededSignalInput extends SignalInputBase {
    source_type: 'endpoint_breakdown_limit_exceeded'
    source_product: 'endpoints'
    extra: EndpointBreakdownLimitExceededSignalExtra
}

// Signals scout — cross-source findings emitted by the headless Signals scout harness.

export interface SignalsScoutEvidenceEntry {
    /** The product the evidence came from, e.g. 'error_tracking', 'logs', 'session_replay'. */
    source_product: string
    /** Optional entity id within that product, e.g. an issue id or session id. */
    entity_id?: string
    /** One-line summary of the evidence the scout used. */
    summary: string
}

export interface SignalsScoutSignalExtra extends SignalExtraBase {
    scout_run_id: string
    /** The `tasks.TaskRun` id the scout span ran inside. Join key into the `signals_scouts_runs`
     * LLM-analytics view, which is keyed on `task_run_id` (the `scout_run_id` bridge row is not). */
    task_run_id: string
    /** The `tasks.Task` id owning `task_run_id`. Pairs with it to deep-link the inbox card to the
     * run in the Tasks UI. Absent on emissions made before this linkage was captured. */
    task_id?: string
    finding_id: string
    skill_name: string
    skill_version: number
    /** Scout's self-reported confidence in [0, 1]. Independent of the top-level `weight`. */
    confidence: number
    severity?: 'P0' | 'P1' | 'P2' | 'P3' | 'P4'
    hypothesis?: string
    evidence: SignalsScoutEvidenceEntry[]
    /** Free-form short keys the harness can use for cross-run dedupe. */
    dedupe_keys?: string[]
    /** Lowercase kebab-case slug tags (e.g. `cost-spike`) categorizing the finding. Each scout
     * maintains and evolves its own vocabulary over time; the harness normalizes and caps these at emit. */
    tags?: string[]
    /** Optional time window the finding refers to. */
    time_range?: {
        date_from: string
        date_to: string
    }
    /** Trace id from the LLM analytics span for the scout run, when available. */
    mcp_trace_id?: string
}

export interface SignalsScoutSignalInput extends SignalInputBase {
    source_type: 'cross_source_issue'
    source_product: 'signals_scout'
    extra: SignalsScoutSignalExtra
}

// Logs alert notification (firing / broken)

export interface LogsAlertStateChangeSignalExtra extends SignalExtraBase {
    alert_id: string
    alert_name: string
    action: 'firing' | 'broken'
    threshold_count: number
    threshold_operator: 'above' | 'below'
    window_minutes: number
    result_count: number | null
    consecutive_failures: number
    filters: Record<string, unknown>
    url: string
}

export interface LogsAlertStateChangeSignalInput extends SignalInputBase {
    source_type: 'alert_state_change'
    source_product: 'logs'
    extra: LogsAlertStateChangeSignalExtra
}

// Replay Vision scanner finding — the optional "side mission" finding a scanner's LLM pass
// may attach to an observation when the scanner has `emits_signals` enabled.

export interface ReplayVisionScannerFindingSignalExtra extends SignalExtraBase {
    scanner_id: string
    scanner_name: string
    /** Replay Vision scanner type, e.g. 'monitor' / 'classifier' / 'scorer' / 'summarizer'. Kept open so new scanner types don't fail signal validation. */
    scanner_type: string
    observation_id: string
    session_id: string
    /** The model's self-reported confidence in the finding, in [0, 1]. Independent of `weight`. */
    confidence: number
    /** Issue category: 'bug' / 'crash' / 'design_flaw' / 'ux_friction'. Kept open so new categories don't fail validation. */
    problem_type: string
    /** When the issue starts in the recording, in seconds from recording start (the footer's REC_T value). */
    start_time: number
    /** When the issue ends in the recording, in seconds (the footer's REC_T value). */
    end_time: number
    /** The page the issue happened on (the footer's URL value). */
    url: string
    /** The rasterized MP4 asset the scanner analysed. */
    exported_asset_id: number
    // Recording-level metadata, present when recording metadata is available. These are the *recording*
    // (snapshot) bounds, which can begin well after the session does depending on customer config —
    // `recording_start_time` is the REC_T=0 anchor for `start_time`/`end_time`.
    distinct_id?: string
    /** ISO 8601 recording start (the REC_T=0 anchor). */
    recording_start_time?: string
    /** ISO 8601 recording end. */
    recording_end_time?: string
    recording_duration?: number
    recording_active_seconds?: number
}

export interface ReplayVisionScannerFindingSignalInput extends SignalInputBase {
    source_type: 'scanner_finding'
    source_product: 'replay_vision'
    extra: ReplayVisionScannerFindingSignalExtra
}

// Health-check issue (instrumentation problem detected by a HealthCheck)

export type HealthCheckSeverity = 'critical' | 'warning' | 'info'

export interface HealthCheckSignalExtra extends SignalExtraBase {
    kind: string
    severity: HealthCheckSeverity
    issue_id: string
    title: string
    summary: string
    /** Relative in-app path to the resource, e.g. '/web'. */
    link: string
    /** Absolute URL ({project.url} + link). */
    url: string
    payload: Record<string, unknown>
}

export interface HealthCheckSignalInput extends SignalInputBase {
    source_type: 'health_issue'
    source_product: 'health_checks'
    extra: HealthCheckSignalExtra
}

// ── Report reviewer types ────────────────────────────────────────────────────────

export interface RelevantCommit {
    sha: string
    url: string
    reason: string
}

export interface SignalReviewerUserInfo {
    id: number
    uuid: string
    first_name: string
    last_name: string
    email: string
}

export interface EnrichedReviewer {
    github_login: string
    github_name: string | null
    relevant_commits: RelevantCommit[]
    user: SignalReviewerUserInfo | null
}

// ── Union over all signal variants ─────────────────────────────────
// Discrimination is handled at the application layer via a (source_product, source_type)
// lookup in products/signals/backend/api.py — see _SIGNAL_VARIANT_LOOKUP. We can't use a
// Pydantic discriminator here because some products (llm_analytics) have multiple variants.

export type SignalInput =
    | SessionProblemSignalInput
    | LlmEvaluationSignalInput
    | LlmEvaluationReportSignalInput
    | ZendeskTicketSignalInput
    | GithubIssueSignalInput
    | LinearIssueSignalInput
    | ConversationsTicketSignalInput
    | ErrorTrackingSignalInput
    | EndpointExecutionFailedSignalInput
    | EndpointBreakdownLimitExceededSignalInput
    | PgAnalyzeIssueSignalInput
    | SignalsScoutSignalInput
    | LogsAlertStateChangeSignalInput
    | HealthCheckSignalInput
    | ReplayVisionScannerFindingSignalInput
