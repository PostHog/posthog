import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils/datetime'

import { MetricsQuery, MetricsQuerySeries } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { TrendsBreakdownAlertPreview } from './trendsAlertPreview'

const compareCodePoints = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

/** Matches `series_label` in the backend metrics extractor, so the preview names a series the way a breach message does. */
export function metricsSeriesLabel(series: MetricsQuerySeries): string {
    const name = series.metricName || series.clause || 'metric'
    const labels = Object.entries(series.labels ?? {}).sort(([a], [b]) => compareCodePoints(a, b))
    return labels.length > 0 ? `${name} {${labels.map(([key, value]) => `${key}=${value}`).join(', ')}}` : name
}

/** Every series on the union of observed buckets, because the alert checks every series on that grid.
 *  A bucket that a series has no value for gets `NaN`, which the chart draws as a gap. */
export function deriveMetricsAlertPreview(
    results: MetricsQuerySeries[] | null | undefined
): TrendsBreakdownAlertPreview | null {
    if (!results || results.length === 0) {
        return null
    }
    const times = Array.from(new Set(results.flatMap((series) => series.points.map((point) => point.time)))).sort(
        compareCodePoints
    )
    return {
        rows: results.map((series, index) => {
            const valueByTime = new Map(series.points.map((point) => [point.time, point.value]))
            return {
                key: String(index),
                label: metricsSeriesLabel(series),
                data: times.map((time) => valueByTime.get(time) ?? NaN),
            }
        }),
        labels: times.map((time) => formatDate(dayjs(time), 'MMM D, HH:mm')),
    }
}

/** The insight interval that sets the default check frequency. Metrics buckets are mostly sub-daily, so hourly is the default. */
export function metricsQueryInsightInterval(query: MetricsQuery): IntervalType {
    if (query.interval === 'day' || query.interval === 'week') {
        return query.interval
    }
    return 'hour'
}
