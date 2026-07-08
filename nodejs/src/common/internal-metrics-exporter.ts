import { Registry, register as globalRegistry } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { FetchResponse, internalFetch } from '~/common/utils/request'

/**
 * Exports this process's prom-client metrics into the PostHog Metrics product
 * (dogfooding): every interval, the registry is snapshotted, converted to an
 * OTLP/JSON `ExportMetricsServiceRequest`, and POSTed to `/i/v1/metrics`. The
 * Prometheus scrape endpoint keeps working untouched — this is an additive sink,
 * off unless `POSTHOG_INTERNAL_METRICS_TOKEN` is set, with a real per-service `service.name`.
 *
 * Prometheus counters/histograms are cumulative, so data points are exported
 * with cumulative temporality and a fixed process-start `startTimeUnixNano` —
 * the metrics read path diffs cumulative series with counter-reset handling.
 */

export interface InternalMetricsConfig {
    host: string
    token: string
    serviceName: string
    intervalSeconds: number
}

interface OtlpKeyValue {
    key: string
    value: { stringValue: string }
}

interface OtlpNumberDataPoint {
    attributes: OtlpKeyValue[]
    startTimeUnixNano: string
    timeUnixNano: string
    asDouble: number
}

interface OtlpHistogramDataPoint {
    attributes: OtlpKeyValue[]
    startTimeUnixNano: string
    timeUnixNano: string
    count: number
    sum: number
    bucketCounts: number[]
    explicitBounds: number[]
}

interface OtlpMetric {
    name: string
    sum?: { aggregationTemporality: number; isMonotonic: boolean; dataPoints: OtlpNumberDataPoint[] }
    gauge?: { dataPoints: OtlpNumberDataPoint[] }
    histogram?: { aggregationTemporality: number; dataPoints: OtlpHistogramDataPoint[] }
}

interface OtlpMetricsPayload {
    resourceMetrics: Array<{
        resource: { attributes: OtlpKeyValue[] }
        scopeMetrics: Array<{ scope: { name: string }; metrics: OtlpMetric[] }>
    }>
}

const OTLP_TEMPORALITY_CUMULATIVE = 2

// Shape of `registry.getMetricsAsJSON()` entries — declared locally because
// prom-client doesn't export its MetricObjectWithValues internals.
interface PromMetric {
    name: string
    type: string
    values: Array<{ value: number; labels: Record<string, string | number>; metricName?: string }>
}

function msToUnixNano(ms: number): string {
    return String(ms) + '000000'
}

function toAttributes(labels: Record<string, string | number>): OtlpKeyValue[] {
    return Object.entries(labels).map(([key, value]) => ({ key, value: { stringValue: String(value) } }))
}

function labelsKey(labels: Record<string, string | number>): string {
    return JSON.stringify(Object.entries(labels).sort(([a], [b]) => (a < b ? -1 : 1)))
}

function convertHistogram(metric: PromMetric, startNano: string, nowNano: string): OtlpHistogramDataPoint[] {
    // prom-client emits one entry per (label set, le) bucket with CUMULATIVE
    // counts, plus `<name>_sum` and `<name>_count` entries per label set.
    // Group by the label set without `le`, then de-cumulate the buckets.
    interface SeriesAccumulator {
        labels: Record<string, string | number>
        buckets: Array<{ le: number; cumulative: number }>
        sum: number
        count: number
    }
    const series = new Map<string, SeriesAccumulator>()

    for (const entry of metric.values) {
        const { le, ...rest } = entry.labels as Record<string, string | number> & { le?: string | number }
        const key = labelsKey(rest)
        let acc = series.get(key)
        if (!acc) {
            acc = { labels: rest, buckets: [], sum: 0, count: 0 }
            series.set(key, acc)
        }
        if (entry.metricName?.endsWith('_sum')) {
            acc.sum = entry.value
        } else if (entry.metricName?.endsWith('_count')) {
            acc.count = entry.value
        } else if (le !== undefined) {
            acc.buckets.push({ le: le === '+Inf' ? Infinity : Number(le), cumulative: entry.value })
        }
    }

    const dataPoints: OtlpHistogramDataPoint[] = []
    for (const acc of series.values()) {
        acc.buckets.sort((a, b) => a.le - b.le)
        const explicitBounds = acc.buckets.filter((b) => Number.isFinite(b.le)).map((b) => b.le)
        const bucketCounts: number[] = []
        let previous = 0
        for (const bucket of acc.buckets) {
            bucketCounts.push(bucket.cumulative - previous)
            previous = bucket.cumulative
        }
        dataPoints.push({
            attributes: toAttributes(acc.labels),
            startTimeUnixNano: startNano,
            timeUnixNano: nowNano,
            count: acc.count,
            sum: acc.sum,
            bucketCounts,
            explicitBounds,
        })
    }
    return dataPoints
}

export function buildOtlpMetricsPayload(
    promMetrics: PromMetric[],
    options: { serviceName: string; startTimeMs: number; nowMs: number }
): OtlpMetricsPayload | null {
    const startNano = msToUnixNano(options.startTimeMs)
    const nowNano = msToUnixNano(options.nowMs)
    const metrics: OtlpMetric[] = []

    for (const metric of promMetrics) {
        if (metric.values.length === 0) {
            continue
        }
        if (metric.type === 'counter') {
            metrics.push({
                name: metric.name,
                sum: {
                    aggregationTemporality: OTLP_TEMPORALITY_CUMULATIVE,
                    isMonotonic: true,
                    dataPoints: metric.values.map((v) => ({
                        attributes: toAttributes(v.labels),
                        startTimeUnixNano: startNano,
                        timeUnixNano: nowNano,
                        asDouble: v.value,
                    })),
                },
            })
        } else if (metric.type === 'gauge') {
            metrics.push({
                name: metric.name,
                gauge: {
                    dataPoints: metric.values.map((v) => ({
                        attributes: toAttributes(v.labels),
                        startTimeUnixNano: startNano,
                        timeUnixNano: nowNano,
                        asDouble: v.value,
                    })),
                },
            })
        } else if (metric.type === 'histogram') {
            const dataPoints = convertHistogram(metric, startNano, nowNano)
            if (dataPoints.length > 0) {
                metrics.push({
                    name: metric.name,
                    histogram: { aggregationTemporality: OTLP_TEMPORALITY_CUMULATIVE, dataPoints },
                })
            }
        }
        // Summaries are skipped: prom-client summaries are rare here and the
        // quantile representation doesn't round-trip losslessly.
    }

    if (metrics.length === 0) {
        return null
    }

    return {
        resourceMetrics: [
            {
                resource: {
                    attributes: toAttributes({ 'service.name': options.serviceName }),
                },
                scopeMetrics: [{ scope: { name: 'posthog-nodejs-internal-metrics' }, metrics }],
            },
        ],
    }
}

export function internalMetricsConfigFromEnv(
    env: Record<string, string | undefined>,
    defaultServiceName: string = 'posthog-nodejs'
): InternalMetricsConfig | null {
    const token = env.POSTHOG_INTERNAL_METRICS_TOKEN
    if (!token) {
        return null
    }
    return {
        token,
        host: env.POSTHOG_INTERNAL_METRICS_HOST || 'https://us.i.posthog.com',
        serviceName: env.POSTHOG_INTERNAL_METRICS_SERVICE_NAME || defaultServiceName,
        intervalSeconds: Number(env.POSTHOG_INTERNAL_METRICS_INTERVAL_SECONDS) || 15,
    }
}

export class InternalMetricsExporter {
    private timer?: NodeJS.Timeout
    private readonly startTimeMs = Date.now()

    constructor(
        private readonly config: InternalMetricsConfig,
        private readonly registry: Registry = globalRegistry,
        private readonly fetchImpl: (
            url: string,
            options: { method: string; headers: Record<string, string>; body: string }
        ) => Promise<Pick<FetchResponse, 'status'>> = internalFetch
    ) {}

    start(): void {
        if (this.timer) {
            return
        }
        this.timer = setInterval(() => void this.exportOnce(), this.config.intervalSeconds * 1000)
        this.timer.unref?.()
        const { token: _token, ...safeConfig } = this.config
        logger.info('📈', 'Internal metrics exporter started', safeConfig)
    }

    stop(): void {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
    }

    private async exportOnce(): Promise<void> {
        try {
            const promMetrics = (await this.registry.getMetricsAsJSON()) as unknown as PromMetric[]
            const payload = buildOtlpMetricsPayload(promMetrics, {
                serviceName: this.config.serviceName,
                startTimeMs: this.startTimeMs,
                nowMs: Date.now(),
            })
            if (!payload) {
                return
            }
            const url = `${this.config.host}/i/v1/metrics?token=${encodeURIComponent(this.config.token)}`
            const response = await this.fetchImpl(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            if (response.status < 200 || response.status >= 300) {
                logger.warn('📈', 'Internal metrics export failed', { status: response.status })
            }
        } catch (error) {
            // Metrics export must never take a service down with it.
            logger.warn('📈', 'Internal metrics export errored', { error })
        }
    }
}

let exporter: InternalMetricsExporter | undefined

/** Starts the exporter once per process if `POSTHOG_INTERNAL_METRICS_TOKEN` is set. */
export function startInternalMetricsExporterFromEnv(defaultServiceName?: string): void {
    if (exporter) {
        return
    }
    const config = internalMetricsConfigFromEnv(process.env, defaultServiceName)
    if (!config) {
        return
    }
    exporter = new InternalMetricsExporter(config)
    exporter.start()
}

/** Stops and clears the process-wide exporter (server shutdown). */
export function stopInternalMetricsExporter(): void {
    exporter?.stop()
    exporter = undefined
}
