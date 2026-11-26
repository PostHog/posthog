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

/** Every series a metrics alert evaluates, mirroring `MetricsExtractor`: the alert fires if any series
 * breaches. `zeroFill` matches the backend, which counts PromQL and SQL gaps as 0; otherwise a gap is `NaN`. */
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
