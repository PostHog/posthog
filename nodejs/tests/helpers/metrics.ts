import { register } from 'prom-client'

export function resetMetrics() {
    register.resetMetrics()
}

export async function getMetricValues(metricName: string): Promise<any> {
    const metrics = await register.getMetricsAsJSON()
    for (const metric of metrics) {
        if (metric.name === metricName) {
            return (metric as any).values
        }
    }
    throw Error(`Metric not found: ${metricName}`)
}
