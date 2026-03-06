// Signal taxonomy types - shared contract between emitters and consumers

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

// Discriminated union over all signal variants

/** @discriminator source_product */
export type SignalInput =
    | SessionSegmentClusterSignalInput
    | LlmEvaluationSignalInput
    | ZendeskTicketSignalInput
    | GithubIssueSignalInput
    | LinearIssueSignalInput
