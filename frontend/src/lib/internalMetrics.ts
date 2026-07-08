import posthog from 'posthog-js'

export interface TimeToSeeDataPayload {
    team_id?: number | null
    type: 'dashboard_load' | 'insight_load' | 'properties_timeline_load' | 'property_values_load' | 'properties_load'
    context: 'dashboard' | 'insight' | 'actors_modal' | 'filters'
    time_to_see_data_ms: number
    primary_interaction_id: string
    query_id?: string
    status?: 'failure' | 'success' | 'cancelled'
    api_response_bytes?: number
    api_url?: string
    insight?: string
    action?: string
    insights_fetched?: number
    insights_fetched_cached?: number
    min_last_refresh?: string | null
    max_last_refresh?: string | null
    // Signifies whether the action was user-initiated or a secondary effect
    is_primary_interaction?: boolean
}

export function currentSessionId(): string | undefined {
    const sessionDetails = posthog.sessionManager?.checkAndGetSessionAndWindowId?.(true)
    return sessionDetails?.sessionId
}
