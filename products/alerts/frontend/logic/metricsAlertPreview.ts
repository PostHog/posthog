import { MetricsQueryResponse, MetricsQuerySeries } from '~/queries/schema/schema-general'

import { TrendsBreakdownAlertPreviewRow } from './trendsAlertPreview'

export interface MetricsAlertPreviewSeries {
    rows: TrendsBreakdownAlertPreviewRow[]
    labels: string[]
}

/** Mirror of `_series_label` in products/alerts/backend/evaluation/metrics.py. */
function metricsSeriesLabel(series: MetricsQuerySeries): string {
    const name = series.metricName || series.clause || 'metric'
    const entries = Object.entries(series.labels ?? {}).sort(([a], [b]) => a.localeCompare(b))
    return entries.length ? `${name} {${entries.map(([key, value]) => `${key}=${value}`).join(', ')}}` : name
}

/** Mirrors `MetricsExtractor`, which counts PromQL and SQL gaps as 0 (`zeroFill`). */
export function deriveMetricsAlertPreviewSeries(
    response: Pick<MetricsQueryResponse, 'results'> | null | undefined,
    zeroFill: boolean
): MetricsAlertPreviewSeries | null {
    if (!Array.isArray(response?.results)) {
        return null
    }
    const series = response.results.filter((row) => Array.isArray(row?.points) && row.points.length)
    const longest = series.reduce<MetricsQuerySeries | null>(
        (acc, row) => (!acc || row.points.length > acc.points.length ? row : acc),
        null
    )
    return {
        rows: series.map((row, index) => ({
            key: String(index),
            label: metricsSeriesLabel(row),
            data: row.points.map((point) => point.value ?? (zeroFill ? 0 : NaN)),
        })),
        labels: longest?.points.map((point) => point.time) ?? [],
    }
}

export function metricsPreviewP95(preview: MetricsAlertPreviewSeries | null | undefined): number | null {
    const values = (preview?.rows ?? [])
        .flatMap((row) => row.data)
        .filter((value) => Number.isFinite(value))
        .sort((a, b) => a - b)
    if (!values.length) {
        return null
    }
    const position = (values.length - 1) * 0.95
    const lower = Math.floor(position)
    const upper = Math.ceil(position)
    const p95 = values[lower] + (values[upper] - values[lower]) * (position - lower)
    if (p95 === 0) {
        return 0
    }
    // Round up to 3 significant figures, so the threshold never sits below the P95.
    const step = 10 ** (Math.floor(Math.log10(Math.abs(p95))) - 2)
    return Number((Math.ceil(p95 / step) * step).toPrecision(3))
}
