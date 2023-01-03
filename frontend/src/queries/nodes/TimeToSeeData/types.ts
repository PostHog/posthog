import { UserBasicType } from '~/types'

export type TimeToSeeNode = TimeToSeeSessionNode | TimeToSeeInteractionNode | TimeToSeeQueryNode

export interface TimeToSeeSessionNode {
    type: 'session'
    data: SessionData
    children: Array<TimeToSeeInteractionNode | TimeToSeeQueryNode>
}

export const isSessionNode = (x: TimeToSeeNode | undefined): x is TimeToSeeSessionNode => {
    return !!x && x.type === 'session'
}

export const isInteractionNode = (x: TimeToSeeNode | undefined): x is TimeToSeeInteractionNode => {
    return ['interaction', 'event'].includes(x?.type || 'not present')
}

export const isQueryNode = (x: TimeToSeeNode | undefined): x is TimeToSeeQueryNode => {
    return ['query', 'subquery'].includes(x?.type || 'not present')
}

export interface TimeToSeeInteractionNode {
    type: 'interaction' | 'event'
    data: InteractionData
    children: Array<TimeToSeeInteractionNode | TimeToSeeQueryNode>
}

export interface TimeToSeeQueryNode {
    type: 'query' | 'subquery'
    data: QueryData
    children: Array<TimeToSeeInteractionNode | TimeToSeeQueryNode>
}

export interface SessionData {
    session_id: string
    user_id: number
    user: UserBasicType
    team_id: number
    session_start: string
    session_end: string
    duration_ms: number

    team_events_last_month: number
    events_count: number
    interactions_count: number
    total_interaction_time_to_see_data_ms: number
    frustrating_interactions_count: number
}

export interface InteractionData {
    query_id: string
    primary_interaction_id: string
    team_id: number
    user_id: number // todo this should be a basic serialized user?
    session_id: string
    min_last_refresh: string
    max_last_refresh: string
    team_events_last_month: number
    timestamp: string
    status: string

    type: string
    context: string
    is_primary_interaction: 0 | 1
    api_response_bytes: number
    time_to_see_data_ms: number
    current_url: string
    api_url: string
    insight: string
    action: string
    insights_fetched: number
    insights_fetched_cached: number

    is_frustrating: 0 | 1
}

export interface QueryData {
    host: string
    timestamp: string

    query_duration_ms: number
    read_rows: number
    read_bytes: number
    result_rows: number
    result_bytes: number
    memory_usage: number
    is_initial_query: 0 | 1
    exception_code: number
    team_id: number
    team_events_last_month: number
    user_id: number
    session_id: string
    kind: string
    query_type: string
    client_query_id: string
    id: string
    route_id: string
    query_time_range_days: number
    has_json_operations: 0 | 1
    filter_by_type: Array<string>
    breakdown_by: Array<string>
    entity_math: Array<string>
    filter: string
    // ProfileEvents Map(String UInt64),
    tables: Array<string>
    columns: Array<string>
    query: string

    log_comment: string

    is_frustrating: 0 | 1

    has_joins: 0 | 1
}
