import type { Series, TimeSeriesBarChartConfig } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

import type { CurrencyCode, GoalLine as SchemaGoalLine, TrendsFilter } from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import { schemaGoalLinesToConfigs } from '../shared/goalLinesAdapter'
import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'
import { COMPARE_PREVIOUS_DIM_OPACITY } from '../trendsAdapterConstants'

// Shape both IndexedTrendResult (kea) and TrendsResultItem (MCP) satisfy.
export interface TrendsBarResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    aggregated_value?: number
    days?: string[]
    compare?: boolean
    compare_label?: string | null
    action?: { order?: number } | null
    breakdown_value?: unknown
    filter?: unknown
}

export interface BuildTrendsBarSeriesOpts<R extends TrendsBarResultLike, M = unknown> {
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

function buildMainTrendsBarSeries<R extends TrendsBarResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildTrendsBarSeriesOpts<R, M>,
    data: number[]
): Series<M> {
    const baseColor = opts.getColor(r, index)
    const color = r.compare_label === 'previous' ? hexToRGBA(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    return {
        key: String(r.id),
        label: r.label ?? '',
        data,
        color,
        meta,
        visibility: excluded ? { excluded: true } : undefined,
    }
}

export function buildTrendsBarTimeSeries<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildMainTrendsBarSeries(r, index, opts, r.data))
}

export interface BuildTrendsBarTimeSeriesConfigOpts {
    trendsFilter?: TrendsFilter | null
    baseCurrency?: CurrencyCode
    isPercentStackView: boolean
    isGrouped: boolean
    yAxisScaleType?: string | null
    interval?: IntervalType | null
    timezone?: string
    allDays?: string[]
    goalLines?: SchemaGoalLine[] | null
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TimeSeriesBarChartConfig['tooltip']
}

// Bar-chart equivalent of buildDerivedConfigs in trends-line-chart: collapses the trends-side
// inputs (display flags, filter, goal-line schema) into a TimeSeriesBarChartConfig. No CI / MA
// / trend lines / inProgress because bar charts don't carry derived series.
export function buildTrendsBarTimeSeriesConfig(opts: BuildTrendsBarTimeSeriesConfigOpts): TimeSeriesBarChartConfig {
    const yAxis = buildTrendsYAxisConfig(opts.trendsFilter, opts.isPercentStackView, opts.baseCurrency, {
        yAxisScaleType: opts.yAxisScaleType,
        showGrid: true,
    })
    const goalLineConfigs = schemaGoalLinesToConfigs(opts.goalLines)
    return {
        xAxis: {
            timezone: opts.timezone,
            interval: opts.interval ?? 'day',
            allDays: opts.allDays ?? [],
        },
        yAxis,
        valueLabels: opts.valueLabels,
        goalLines: goalLineConfigs,
        barLayout: opts.isPercentStackView ? 'percent' : opts.isGrouped ? 'grouped' : 'stacked',
        tooltip: opts.tooltip,
    }
}

// Sparse-stacked: hog-charts BarChart allows one color per series, so we emit N series with
// data=0 except at their own band — d3.stack reduces this to one visible segment per band.
// Trade-off: only the last series gets rounded-corner caps.
export function buildTrendsBarAggregatedSeries<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarSeriesOpts<R, M>
): { series: Series<M>[]; labels: string[] } {
    // Hidden results are dropped entirely — keeping them as `excluded` series would leave
    // a phantom band on the category axis with no bar.
    const visible = opts.getHidden ? results.filter((r, i) => !opts.getHidden!(r, i)) : results
    const labels = visible.map((r) => r.label ?? '')
    const n = visible.length
    const series = visible.map((r, index) => {
        const data = new Array<number>(n).fill(0)
        const value = r.aggregated_value ?? 0
        if (Number.isFinite(value)) {
            data[index] = value
        }
        return buildMainTrendsBarSeries(r, index, opts, data)
    })
    return { series, labels }
}
