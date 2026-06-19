import { type MetricChange } from '@posthog/quill-charts'

// Above this magnitude the exact percentage is noise (it comes from a near-zero start), so show ∞ instead.
export const MAX_CHANGE_PERCENT = 10_000 // ≈100×

export type MetricSummary = 'total' | 'average' | 'latest'

export const METRIC_SUMMARY_DEFAULT: MetricSummary = 'total'
export const METRIC_SUMMARY_LABELS: Record<MetricSummary, string> = {
    total: 'Total',
    average: 'Avg',
    latest: 'Latest',
}

export const METRIC_SHOW_CHANGE_DEFAULT = true
export const METRIC_COLOR_BY_DIRECTION_DEFAULT = false
export const METRIC_DEFAULT_INCREASE_COLOR = '#388600'
export const METRIC_DEFAULT_DECREASE_COLOR = '#db3707'

const finiteValues = (data: number[] | undefined): number[] => (data ?? []).filter((v) => Number.isFinite(v))

const meanOfFinite = (data: number[] | undefined): number | undefined => {
    const finite = finiteValues(data)
    return finite.length === 0 ? undefined : finite.reduce((sum, v) => sum + v, 0) / finite.length
}

// Percentage change from `start` to `end`. Renders ∞ when the start is zero (infinite) or the magnitude
// is so large the exact percentage is just noise. A missing endpoint yields `undefined` (no pill).
function changeBetween(start: number | undefined, end: number | undefined): MetricChange | null | undefined {
    if (start == null || end == null) {
        return undefined
    }
    if (start === 0) {
        return end === 0 ? null : { value: end > 0 ? 1 : -1, label: '∞' }
    }
    const percent = ((end - start) / Math.abs(start)) * 100
    return Math.abs(percent) >= MAX_CHANGE_PERCENT ? { value: percent, label: '∞' } : { value: percent }
}

// Change from the first to the last finite point of a single series.
export function computeMetricChange(data: number[] | undefined): MetricChange | null | undefined {
    const finite = finiteValues(data)
    return finite.length < 2 ? undefined : changeBetween(finite[0], finite[finite.length - 1])
}

// Resting headline shown when the user isn't hovering a point. `total` is the series aggregate
// (`resultSeries.count`); `average`/`latest` are derived from the finite sparkline points.
export function computeMetricSummary(summary: MetricSummary, total: number, data: number[] | undefined): number {
    if (summary === 'total') {
        return total
    }
    const finite = finiteValues(data)
    if (finite.length === 0) {
        return total
    }
    return summary === 'latest' ? finite[finite.length - 1] : finite.reduce((sum, v) => sum + v, 0) / finite.length
}

export interface MetricSeriesSummary {
    total: number
    data: number[] | undefined
}

// The change pill, matched to the chosen summary:
//  - `total`/`average` with a comparison period → this period's total/average vs the previous period's.
//  - `latest`, or `total`/`average` without a comparison period → first → last of the current series.
export function computeMetricSummaryChange(
    summary: MetricSummary,
    current: MetricSeriesSummary,
    previous: MetricSeriesSummary | undefined
): MetricChange | null | undefined {
    if (previous && summary !== 'latest') {
        return summary === 'total'
            ? changeBetween(previous.total, current.total)
            : changeBetween(meanOfFinite(previous.data), meanOfFinite(current.data))
    }
    return computeMetricChange(current.data)
}
