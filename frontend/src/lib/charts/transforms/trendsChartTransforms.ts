import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

import { ChartDisplayType } from '~/types'

const COMPARE_PREVIOUS_DIM_OPACITY = 0.5

// Shape both IndexedTrendResult (kea) and TrendsResultItem (MCP) satisfy.
export interface TrendsResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    days?: string[]
    compare?: boolean
    compare_label?: string | null
    action?: { order?: number } | null
    breakdown_value?: unknown
    filter?: unknown
}

export interface BuildTrendsSeriesOpts<R extends TrendsResultLike, M = unknown> {
    display?: ChartDisplayType
    showMultipleYAxes?: boolean
    // Negative number — index from the end where the in-progress tail begins. Omit to skip.
    incompletenessOffsetFromEnd?: number
    isStickiness?: boolean
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

export interface BuiltTrendsSeries<M> {
    main: Series<M>
    // Un-dimmed base color, exposed so derived series can dim further without re-resolving.
    baseColor: string
    dashedFromIndex: number | undefined
    excluded: boolean
}

export function buildMainTrendsSeries<R extends TrendsResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildTrendsSeriesOpts<R, M>
): BuiltTrendsSeries<M> {
    const isActiveSeries = !r.compare || r.compare_label !== 'previous'
    const isInProgress =
        !opts.isStickiness && opts.incompletenessOffsetFromEnd !== undefined && opts.incompletenessOffsetFromEnd < 0
    const dashedFromIndex =
        isInProgress && isActiveSeries ? r.data.length + (opts.incompletenessOffsetFromEnd as number) : undefined
    const yAxisId = opts.showMultipleYAxes && index > 0 ? `y${index}` : DEFAULT_Y_AXIS_ID
    const baseColor = opts.getColor(r, index)
    const displayColor = r.compare_label === 'previous' ? hexToRGBA(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta: M | undefined = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    const main: Series<M> = {
        key: String(r.id),
        label: r.label ?? '',
        data: r.data,
        color: displayColor,
        yAxisId,
        meta,
        fill: opts.display === ChartDisplayType.ActionsAreaGraph ? {} : undefined,
        stroke: dashedFromIndex !== undefined ? { partial: { fromIndex: dashedFromIndex } } : undefined,
        visibility: excluded ? { excluded: true } : undefined,
    }
    return { main, baseColor, dashedFromIndex, excluded }
}

export function buildTrendsSeries<R extends TrendsResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsSeriesOpts<R, M>
): BuiltTrendsSeries<M>[] {
    return results.map((r, i) => buildMainTrendsSeries(r, i, opts))
}

export interface BuildTrendsChartConfigOpts {
    // Anything other than 'log10' is treated as linear.
    yAxisScaleType?: string | null
    isPercentStackView?: boolean
    showCrosshair?: boolean
    showGrid?: boolean
    pinnableTooltip?: boolean
    tooltipPlacement?: 'top' | 'follow-data'
    xTickFormatter?: (value: string | number, index: number) => string | null
    yTickFormatter?: (value: number) => string
}

// Undefined keys fall through to hog-charts defaults — don't add fallbacks here.
export function buildTrendsChartConfig(opts: BuildTrendsChartConfigOpts): LineChartConfig {
    const tooltip =
        opts.pinnableTooltip !== undefined || opts.tooltipPlacement !== undefined
            ? { pinnable: opts.pinnableTooltip, placement: opts.tooltipPlacement }
            : undefined
    const yScaleType: 'linear' | 'log' = opts.yAxisScaleType === 'log10' ? 'log' : 'linear'
    return {
        showGrid: opts.showGrid,
        showCrosshair: opts.showCrosshair,
        tooltip,
        yScaleType,
        percentStackView: opts.isPercentStackView,
        xTickFormatter: opts.xTickFormatter,
        yTickFormatter: opts.yTickFormatter,
    }
}
