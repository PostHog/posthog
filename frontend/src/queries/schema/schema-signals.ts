// Signal taxonomy types - shared contract between emitters and consumers

// Common fields shared by all signal inputs
interface SignalInputBase {
    source_id: string
    description: string
    weight: number
}

// Session replay segment cluster

export interface SessionReplaySegment {
    session_id: string
    start_time: string
    end_time: string
    distinct_id: string
    content: string
}

export interface SessionSegmentClusterMetrics {
    relevant_user_count: number
    active_users_in_period: number
    occurrence_count: number
}

export interface SessionSegmentClusterSignalExtra {
    label_title: string
    actionable: boolean
    segments: SessionReplaySegment[]
    metrics: SessionSegmentClusterMetrics
}

export interface SessionSegmentClusterSignalInput extends SignalInputBase {
    source_type: 'session_segment_cluster'
    source_product: 'session_replay'
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

export interface LlmEvaluationSignalInput extends SignalInputBase {
    source_type: 'evaluation'
    source_product: 'llm_analytics'
    extra: LlmEvalSignalExtra
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

export interface ZendeskTicketSignalInput extends SignalInputBase {
    source_type: 'ticket'
    source_product: 'zendesk'
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

export interface GithubIssueSignalInput extends SignalInputBase {
    source_type: 'issue'
    source_product: 'github'
    extra: GithubIssueSignalExtra
}

// Error tracking

export interface ErrorTrackingNewExceptionSignalExtra {
    issue_id: string
    fingerprint: string
}

export interface ErrorTrackingNewExceptionSignalInput extends SignalInputBase {
    source_type: 'new_exception'
    source_product: 'error_tracking'
    extra: ErrorTrackingNewExceptionSignalExtra
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

export interface LinearIssueSignalInput extends SignalInputBase {
    source_type: 'issue'
    source_product: 'linear'
    extra: LinearIssueSignalExtra
}

// Discriminated union over all signal variants

/** @discriminator source_product */
export type SignalInput =
    | SessionSegmentClusterSignalInput
    | LlmEvaluationSignalInput
    | ZendeskTicketSignalInput
    | GithubIssueSignalInput
    | LinearIssueSignalInput
    | ErrorTrackingNewExceptionSignalInput
