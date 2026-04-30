import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

import { ChartDisplayType } from '~/types'

/**
 * Narrow shape both IndexedTrendResult (kea) and TrendsResultItem (MCP)
 * satisfy. Type the inputs against this so the module never touches the
 * kea-specific superset.
 */
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
    /**
     * Negative number — index from the end where the in-progress (dashed)
     * tail begins. Mirrors LineGraph.tsx semantics. Pass undefined to
     * skip the dashed tail entirely (MCP).
     */
    incompletenessOffsetFromEnd?: number
    isStickiness?: boolean
    /** Resolve the base color for a series. Kea passes getTrendsColor;
     *  MCP passes a palette function. */
    getColor: (r: R, index: number) => string
    /** Optional hidden gate. Returns true if the series should be hidden. */
    getHidden?: (r: R, index: number) => boolean
    /** Build the meta payload attached to the main series. */
    buildMeta?: (r: R, index: number) => M
}

/**
 * Result of building a main series. Returned alongside the helpful
 * pre-computed values so the caller can build derived series (CI bands,
 * moving averages, trend lines) without recomputing color / yAxisId /
 * dashedFromIndex / excluded from scratch.
 */
export interface BuiltTrendsSeries<M> {
    main: Series<M>
    /** The original (un-dimmed) base color from getColor. Useful for
     *  derived series that want to dim further with hexToRGBA. */
    baseColor: string
    /** Where the dashed in-progress tail starts on this series, if any.
     *  Already null for compare-previous and stickiness. */
    dashedFromIndex: number | undefined
    excluded: boolean
}

/**
 * Build the main canvas series for a single trends result. Mirrors the
 * inline construction in TrendsLineChart.tsx — same color dimming for
 * compare-previous, same dashed tail logic, same yAxisId selection,
 * same fill toggle for ActionsAreaGraph.
 */
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
    const displayColor = r.compare_label === 'previous' ? hexToRGBA(baseColor, 0.5) : baseColor
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

/**
 * Convenience: build main series for every result. Caller still needs to
 * append derived series (CI / MA / TL) themselves if desired.
 */
export function buildTrendsSeries<R extends TrendsResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsSeriesOpts<R, M>
): BuiltTrendsSeries<M>[] {
    return results.map((r, i) => buildMainTrendsSeries(r, i, opts))
}

export interface BuildTrendsChartConfigOpts {
    yScaleType?: 'linear' | 'log10'
    isPercentStackView?: boolean
    showCrosshair?: boolean
    showGrid?: boolean
    pinnableTooltip?: boolean
    tooltipPlacement?: 'top' | 'follow-data'
    xTickFormatter?: (value: string | number, index: number) => string | null
    yTickFormatter?: (value: number) => string
}

/**
 * Build the LineChartConfig from a flat options bag. No defaults are
 * applied for keys the caller didn't pass — they fall through to
 * undefined so hog-charts uses its own defaults.
 */
export function buildTrendsChartConfig(opts: BuildTrendsChartConfigOpts): LineChartConfig {
    const tooltip =
        opts.pinnableTooltip !== undefined || opts.tooltipPlacement !== undefined
            ? { pinnable: opts.pinnableTooltip, placement: opts.tooltipPlacement }
            : undefined
    const yScaleType: 'linear' | 'log' | undefined = opts.yScaleType === 'log10' ? 'log' : opts.yScaleType
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
