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
