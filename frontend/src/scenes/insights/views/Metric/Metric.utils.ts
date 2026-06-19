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

const mean = (values: number[]): number => values.reduce((sum, v) => sum + v, 0) / values.length

const meanOfFinite = (data: number[] | undefined): number | undefined => {
    const finite = finiteValues(data)
    return finite.length === 0 ? undefined : mean(finite)
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

export function computeMetricChange(data: number[] | undefined): MetricChange | null | undefined {
    const finite = finiteValues(data)
    return finite.length < 2 ? undefined : changeBetween(finite[0], finite[finite.length - 1])
}

// Falls back to the total when the series has no finite points.
export function computeMetricSummary(summary: MetricSummary, total: number, data: number[] | undefined): number {
    if (summary === 'total') {
        return total
    }
    const finite = finiteValues(data)
    if (finite.length === 0) {
        return total
    }
    return summary === 'latest' ? finite[finite.length - 1] : mean(finite)
}

export interface MetricSeriesSummary {
    total: number
    data: number[] | undefined
}

interface ComparableSeries {
    count: number
    data: number[]
    compare_label?: string | null
}

// The previous comparison period, when "compare to previous" is on. Matched by `compare_label` rather
// than position so it stays correct if the results array ever holds more than the current series.
export function selectPreviousSeriesSummary(
    compareEnabled: boolean,
    results: readonly ComparableSeries[] | undefined
): MetricSeriesSummary | undefined {
    if (!compareEnabled || !results) {
        return undefined
    }
    const previous = results.find((series) => series.compare_label === 'previous')
    return previous ? { total: previous.count, data: previous.data } : undefined
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

// Plain-language description of what the change pill compares, for a tooltip — keyed to the branches in
// `computeMetricSummaryChange`. `total`/`average` apply only with a comparison period; otherwise (and
// always for `latest`) the pill is the within-period first→last movement.
export const METRIC_CHANGE_TOOLTIPS = {
    total: "Comparing this period's total to the previous period's total.",
    average: "Comparing this period's average to the previous period's average.",
    firstToLatest: 'Comparing the first value in this period to the most recent value.',
}
