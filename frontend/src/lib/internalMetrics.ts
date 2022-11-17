import posthog from 'posthog-js'
import api from 'lib/api'

interface InternalMetricsPayload {
    method: 'incr' | 'timing'
    metric: string
    value: number
    tags: Record<string, any>
}

interface TimeToSeeDataPayload {
    query_id: string
    status: 'failure' | 'success'
    time_to_see_data_ms: number
    cached: boolean
    current_url: string
    api_response_bytes?: number
    api_url?: string
    insight: string
}

export async function captureInternalMetric(payload: InternalMetricsPayload): Promise<void> {
    if (window.JS_CAPTURE_INTERNAL_METRICS) {
        await api.create('api/instance_status/capture', payload)
    }
}

export async function captureTimeToSeeData(teamId: number, payload: TimeToSeeDataPayload): Promise<void> {
    if (window.JS_CAPTURE_TIME_TO_SEE_DATA) {
        const sessionDetails = posthog.sessionManager?.checkAndGetSessionAndWindowId?.(true)

        await api.create(`api/projects/${teamId}/insights/timing`, {
            session_id: sessionDetails?.sessionId ?? '',
            ...payload,
        })
    }
}
