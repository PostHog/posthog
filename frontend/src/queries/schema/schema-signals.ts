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
