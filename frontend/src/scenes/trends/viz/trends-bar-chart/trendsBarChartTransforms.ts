import type { BarChartConfig, Series } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

const COMPARE_PREVIOUS_DIM_OPACITY = 0.5

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

export function buildMainTrendsBarSeries<R extends TrendsBarResultLike, M = unknown>(
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

/** Vertical bars: each result is a series with values across time (the same shape the line chart uses). */
export function buildTrendsBarTimeSeries<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildMainTrendsBarSeries(r, index, opts, r.data))
}

export interface BuildTrendsBarChartConfigOpts {
    // Anything other than 'log10' is treated as linear.
    yAxisScaleType?: string | null
    isPercentStackView?: boolean
    axisOrientation?: 'vertical' | 'horizontal'
    showGrid?: boolean
    pinnableTooltip?: boolean
    tooltipPlacement?: 'top' | 'follow-data'
    xTickFormatter?: (value: string | number, index: number) => string | null
    yTickFormatter?: (value: number) => string
}

// Undefined keys fall through to hog-charts defaults — don't add fallbacks here.
export function buildTrendsBarChartConfig(opts: BuildTrendsBarChartConfigOpts): BarChartConfig {
    const tooltip =
        opts.pinnableTooltip !== undefined || opts.tooltipPlacement !== undefined
            ? { pinnable: opts.pinnableTooltip, placement: opts.tooltipPlacement }
            : undefined
    const yScaleType: 'linear' | 'log' = opts.yAxisScaleType === 'log10' ? 'log' : 'linear'
    const barLayout: 'stacked' | 'percent' = opts.isPercentStackView ? 'percent' : 'stacked'
    return {
        showGrid: opts.showGrid,
        tooltip,
        yScaleType,
        axisOrientation: opts.axisOrientation,
        barLayout,
        xTickFormatter: opts.xTickFormatter,
        yTickFormatter: opts.yTickFormatter,
    }
}
