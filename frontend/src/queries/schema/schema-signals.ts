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
    CROSS_SOURCE_ISSUE = 'cross_source_issue',
    ALERT_STATE_CHANGE = 'alert_state_change',
}

// ── Shared optional remediation ──────────────────────────────────────────────────
// A known fix attached to a signal. Optional and separate from `extra`: `extra` is product-specific
// evidence; `remediation` is guidance for the research agent. When present, the signal is treated as
// actionable and the agent follows the guidance rather than investigating from scratch — it still
// runs, produces findings, and writes the human-facing report. Every variant may carry it.

export interface SignalRemediation {
    /** Agent-facing guidance: how to investigate (which MCP tools to call) and, where the fix lives
     *  in the user's codebase, how to apply it. The research agent treats this as authoritative — it
     *  still investigates and produces findings, but follows this instead of starting cold. */
    agent: string
    /** Suggested report priority (advisory — the research agent may override). */
    priority?: 'P0' | 'P1' | 'P2' | 'P3' | 'P4'
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

export interface SessionProblemSignalExtra {
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

export interface SessionProblemSignalInput {
    source_type: 'session_problem'
    source_product: 'session_replay'
    source_id: string
    description: string
    weight: number
    extra: SessionProblemSignalExtra
    remediation?: SignalRemediation
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
export interface SessionSegmentClusterSignalExtra {
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

export interface LlmEvalSignalExtra {
    evaluation_id: string
    target_event_id?: string
    target_event_type?: string
    trace_id: string
    model?: string
    provider?: string
}

export interface LlmEvaluationSignalInput {
    source_type: 'evaluation'
    source_product: 'llm_analytics'
    source_id: string
    description: string
    weight: number
    extra: LlmEvalSignalExtra
    remediation?: SignalRemediation
}

// LLM evaluation report (one signal per report run, distilled from many results)

export interface LlmEvalReportSignalExtra {
    evaluation_id: string
    evaluation_name: string
    evaluation_description: string
    report_id: string
    report_run_id: string
    period_start: string
    period_end: string
}

export interface LlmEvaluationReportSignalInput {
    source_type: 'evaluation_report'
    source_product: 'llm_analytics'
    source_id: string
    description: string
    weight: number
    extra: LlmEvalReportSignalExtra
    remediation?: SignalRemediation
}

// Zendesk ticket

export interface ZendeskTicketSignalExtra {
    url: string
    type: string | null
    tags: string[]
    created_at: string
    priority: string | null
    status: string
}

export interface ZendeskTicketSignalInput {
    source_type: 'ticket'
    source_product: 'zendesk'
    source_id: string
    description: string
    weight: number
    extra: ZendeskTicketSignalExtra
    remediation?: SignalRemediation
}

// GitHub issue

export interface GithubIssueSignalExtra {
    html_url: string
    number: number
    labels: string[]
    created_at: string
    updated_at: string
    locked: boolean
    state: string
}

export interface GithubIssueSignalInput {
    source_type: 'issue'
    source_product: 'github'
    source_id: string
    description: string
    weight: number
    extra: GithubIssueSignalExtra
    remediation?: SignalRemediation
}

// Linear issue

export interface LinearIssueSignalExtra {
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

export interface LinearIssueSignalInput {
    source_type: 'issue'
    source_product: 'linear'
    source_id: string
    description: string
    weight: number
    extra: LinearIssueSignalExtra
    remediation?: SignalRemediation
}

// Conversations ticket

export interface ConversationsTicketSignalExtra {
    ticket_number: number
    channel_source: string
    channel_detail: string | null
    status: string
    priority: string | null
    created_at: string
    email_subject: string | null
}

export interface ConversationsTicketSignalInput {
    source_type: 'ticket'
    source_product: 'conversations'
    source_id: string
    description: string
    weight: number
    extra: ConversationsTicketSignalExtra
    remediation?: SignalRemediation
}

// Error tracking

export interface ErrorTrackingSignalExtra {
    fingerprint: string
}

export interface ErrorTrackingSignalInput {
    source_type: 'issue_created' | 'issue_reopened' | 'issue_spiking'
    source_product: 'error_tracking'
    source_id: string
    description: string
    weight: number
    extra: ErrorTrackingSignalExtra
    remediation?: SignalRemediation
}

// pganalyze issue (database performance finding)

export interface PgAnalyzeIssueReference {
    kind: string | null
    name: string | null
    url: string | null
    queryText: string | null
}

export interface PgAnalyzeIssueSignalExtra {
    severity: string | null
    references: PgAnalyzeIssueReference[]
    database_id: string | null
    server_human_id: string | null
    server_name: string | null
    synced_at: string
}

export interface PgAnalyzeIssueSignalInput {
    source_type: 'issue'
    source_product: 'pganalyze'
    source_id: string
    description: string
    weight: number
    extra: PgAnalyzeIssueSignalExtra
    remediation?: SignalRemediation
}

// Endpoint execution failure

export interface EndpointExecutionFailedSignalExtra {
    endpoint_name: string
    endpoint_version: number | null
    materialized: boolean
    saved_query_id: string | null
    error_class: string
    error_message: string
}

export interface EndpointExecutionFailedSignalInput {
    source_type: 'endpoint_execution_failed'
    source_product: 'endpoints'
    source_id: string
    description: string
    weight: number
    extra: EndpointExecutionFailedSignalExtra
    remediation?: SignalRemediation
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

export interface SignalsScoutSignalExtra {
    scout_run_id: string
    /** The `tasks.TaskRun` id the scout span ran inside. Join key into the `signals_scouts_runs`
     * LLM-analytics view, which is keyed on `task_run_id` (the `scout_run_id` bridge row is not). */
    task_run_id: string
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
    /** Optional time window the finding refers to. */
    time_range?: {
        date_from: string
        date_to: string
    }
    /** Trace id from the LLM analytics span for the scout run, when available. */
    mcp_trace_id?: string
}

export interface SignalsScoutSignalInput {
    source_type: 'cross_source_issue'
    source_product: 'signals_scout'
    source_id: string
    description: string
    weight: number
    extra: SignalsScoutSignalExtra
    remediation?: SignalRemediation
}

// Logs alert notification (firing / broken)

export interface LogsAlertStateChangeSignalExtra {
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

export interface LogsAlertStateChangeSignalInput {
    source_type: 'alert_state_change'
    source_product: 'logs'
    source_id: string
    description: string
    weight: number
    extra: LogsAlertStateChangeSignalExtra
    remediation?: SignalRemediation
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
    | PgAnalyzeIssueSignalInput
    | SignalsScoutSignalInput
    | LogsAlertStateChangeSignalInput
