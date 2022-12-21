import posthog from 'posthog-js'
import api from 'lib/api'

export interface TimeToSeeDataPayload {
    type: 'insight_load' | 'dashboard_load'
    context: 'insight' | 'dashboard'
    time_to_see_data_ms: number
    dashboard_query_id?: string
    query_id?: string
    status?: 'failure' | 'success' | 'cancelled'
    api_response_bytes?: number
    api_url?: string
    insight?: string
    action?: string
    insights_fetched: number
    insights_fetched_cached: number
    min_last_refresh?: string | null
    max_last_refresh?: string | null
    // Signifies whether the action was user-initiated or a secondary effect
    is_primary_interaction?: boolean
}

export function currentSessionId(): string | undefined {
    const sessionDetails = posthog.sessionManager?.checkAndGetSessionAndWindowId?.(true)
    return sessionDetails?.sessionId
}

export async function captureTimeToSeeData(teamId: number | null, payload: TimeToSeeDataPayload): Promise<void> {
    if (window.JS_CAPTURE_TIME_TO_SEE_DATA && teamId) {
        await api.create(`api/projects/${teamId}/insights/timing`, {
            session_id: currentSessionId(),
            current_url: window.location.href,
            ...payload,
        })
    }
}
