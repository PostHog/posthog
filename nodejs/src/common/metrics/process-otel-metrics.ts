import { metrics as metricsApi } from '@opentelemetry/api'
import { EventLoopUtilization, performance } from 'perf_hooks'

/**
 * Process resource usage pushed to the PostHog metrics product. The prom side of
 * these already exists (prom-client collectDefaultMetrics + event_loop_utilization
 * in node-instrumentation.ts) and keeps feeding the scrape/VictoriaMetrics
 * dashboards; names match so a CPU/memory panel translates 1:1.
 *
 * Registered from initMetrics only when OTLP export is enabled, so nothing is
 * observed (or even sampled) for deployments that don't opt in.
 */

export const cpuUsageSeconds = (usage: { user: number; system: number }): number => (usage.user + usage.system) / 1e6

let registered = false
let lastEventLoopUtilization: EventLoopUtilization | null = null

export function registerProcessOtelMetrics(): void {
    if (registered) {
        return
    }
    registered = true

    const meter = metricsApi.getMeter('nodejs-process')

    meter
        .createObservableCounter('process_cpu_seconds_total', {
            description: 'Total user and system CPU time spent by the process in seconds.',
            unit: 's',
        })
        .addCallback((result) => {
            result.observe(cpuUsageSeconds(process.cpuUsage()))
        })

    meter
        .createObservableGauge('process_resident_memory_bytes', {
            description: 'Resident memory size of the process in bytes.',
            unit: 'By',
        })
        .addCallback((result) => {
            result.observe(process.memoryUsage.rss())
        })

    meter
        .createObservableGauge('event_loop_utilization', {
            description: 'Proportion of time the event loop was busy since the previous export.',
        })
        .addCallback((result) => {
            const current = performance.eventLoopUtilization()
            const delta = lastEventLoopUtilization
                ? performance.eventLoopUtilization(current, lastEventLoopUtilization)
                : current
            lastEventLoopUtilization = current
            result.observe(delta.utilization)
        })
}

/** Test seam: allow re-registration against a test-installed provider. */
export function resetProcessOtelMetricsForTests(): void {
    registered = false
    lastEventLoopUtilization = null
}
