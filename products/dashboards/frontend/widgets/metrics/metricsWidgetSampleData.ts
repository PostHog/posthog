import type { MetricsHistogramQueryResponse, MetricsQuery, MetricsQueryResponse } from '~/queries/schema/schema-general'

import type { MetricsWidgetPresetId } from './metricsWidgetConfig'
import { METRICS_WIDGET_PRESETS, metricsWidgetDefaultConfig } from './metricsWidgetConfig'

// Fixed sample data: previews and stories must render the same chart on every run.
const SAMPLE_START = Date.UTC(2026, 0, 15, 9, 0)
const SAMPLE_STEP_MS = 5 * 60 * 1000
const SAMPLE_BUCKETS = 24

const sampleTimes = Array.from({ length: SAMPLE_BUCKETS }, (_, index) =>
    new Date(SAMPLE_START + index * SAMPLE_STEP_MS).toISOString()
)

function sampleSeries(service: string, base: number, swing: number): MetricsQueryResponse['results'][number] {
    return {
        labels: { 'service.name': service },
        metricName: 'http_server_requests',
        unit: '{request}/s',
        points: sampleTimes.map((time, index) => ({
            time,
            value: Math.round(base + swing * Math.sin(index / 3) + (index % 4) * swing * 0.1),
        })),
    }
}

export const METRICS_WIDGET_SAMPLE_RESPONSE: MetricsQueryResponse = {
    results: [sampleSeries('checkout', 120, 30), sampleSeries('api-gateway', 260, 45), sampleSeries('search', 80, 20)],
}

const SAMPLE_BOUNDS = [5, 10, 25, 50, 100, 250, 500]

export const METRICS_WIDGET_SAMPLE_HISTOGRAM_RESPONSE: MetricsHistogramQueryResponse = {
    results: null,
    times: sampleTimes,
    bounds: SAMPLE_BOUNDS,
    counts: SAMPLE_BOUNDS.map((_, row) =>
        sampleTimes.map((_, column) => Math.max(0, Math.round(40 * Math.exp(-((row - 3 - Math.sin(column / 4)) ** 2)))))
    ),
}

const METRICS_WIDGET_SAMPLE_TOTAL_RESPONSE: MetricsQueryResponse = {
    results: [{ ...sampleSeries('checkout', 460, 60), labels: {} }],
}

export function metricsWidgetSampleQuery(presetId: MetricsWidgetPresetId): MetricsQuery {
    const preset = METRICS_WIDGET_PRESETS.find((candidate) => candidate.id === presetId) ?? METRICS_WIDGET_PRESETS[0]
    const { query } = metricsWidgetDefaultConfig(preset.display) as { query: MetricsQuery }
    const clause =
        preset.id === 'heatmap'
            ? { name: 'a', metricName: 'http_server_request_duration', metricType: 'histogram' as const }
            : preset.id === 'stat'
              ? {
                    name: 'a',
                    metricName: 'http_server_requests',
                    rangeFunction: 'rate' as const,
                    aggregation: 'sum' as const,
                }
              : {
                    name: 'a',
                    metricName: 'http_server_requests',
                    rangeFunction: 'rate' as const,
                    aggregation: 'sum' as const,
                    groupBy: [{ key: 'service.name' }],
                }
    return { ...query, clauses: [clause] }
}

export function metricsWidgetSampleResponse(
    presetId: MetricsWidgetPresetId
): MetricsQueryResponse | MetricsHistogramQueryResponse {
    if (presetId === 'heatmap') {
        return METRICS_WIDGET_SAMPLE_HISTOGRAM_RESPONSE
    }
    return presetId === 'stat' ? METRICS_WIDGET_SAMPLE_TOTAL_RESPONSE : METRICS_WIDGET_SAMPLE_RESPONSE
}
