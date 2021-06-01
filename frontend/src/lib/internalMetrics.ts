import api from 'lib/api'

interface InternalMetricsPayload {
    method: 'incr' | 'timing'
    metric: string
    value: number
    tags: Record<string, any>
}

export function captureInternalMetric(payload: InternalMetricsPayload): Promise<void> {
    return api.create('api/instance_status/capture', payload)
}
