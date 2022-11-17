import api from 'lib/api'

interface InternalMetricsPayload {
    method: 'incr' | 'timing'
    metric: string
    value: number
    tags: Record<string, any>
}

export async function captureInternalMetric(payload: InternalMetricsPayload): Promise<void> {
    if (window.JS_CAPTURE_INTERNAL_METRICS) {
        await api.create('api/instance_status/capture', payload)
    }
}

export async function captureTimeToSeeData(teamId: number, payload: Record<string, any>): Promise<void> {
    if (window.JS_CAPTURE_TIME_TO_SEE_DATA) {
        await api.create(`api/projects/${teamId}/insights/timing`, payload)
        console.log(teamId, payload)
    }
}
