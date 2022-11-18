import posthog from 'posthog-js'
import api from 'lib/api'

interface InternalMetricsPayload {
    method: 'incr' | 'timing'
    metric: string
    value: number
    tags: Record<string, any>
}

interface TimeToSeeDataPayload {
    type: 'insight_load' | 'dashboard_load'
    context: 'insight' | 'dashboard'
    time_to_see_data_ms: number
    dashboard_query_id?: string
    query_id?: string
    status?: 'failure' | 'success'
    api_response_bytes?: number
    api_url?: string
    insight?: string
    action?: string
    insights_fetched: number
    insights_fetched_cached: number
    min_last_refresh?: string | null
    max_last_refresh?: string | null
}

export async function captureInternalMetric(payload: InternalMetricsPayload): Promise<void> {
    if (window.JS_CAPTURE_INTERNAL_METRICS) {
        await api.create('api/instance_status/capture', payload)
    }
}

export async function captureTimeToSeeData(teamId: number | null, payload: TimeToSeeDataPayload): Promise<void> {
    if (window.JS_CAPTURE_TIME_TO_SEE_DATA) {
        const sessionDetails = posthog.sessionManager?.checkAndGetSessionAndWindowId?.(true)

        await api.create(`api/projects/${teamId}/insights/timing`, {
            session_id: sessionDetails?.sessionId ?? '',
            current_url: window.location.href,
            ...payload,
        })
    }
}
