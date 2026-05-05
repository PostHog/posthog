import { DEFAULT_Y_AXIS_ID, movingAverageKey } from 'lib/hog-charts'
import type { ConfidenceIntervalConfig, MovingAverageConfig, Series, TrendLineConfig } from 'lib/hog-charts'
import { ciRanges } from 'lib/statistics'

import { ChartDisplayType } from '~/types'

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

/** Compute the in-progress dashed-tail boundary for a single result. Returns the index
 *  the partial styling should start at, or `undefined` if the series gets no partial.
 *  Compare-previous series are historical and always return `undefined`. Shared between
 *  the main-series builder (for `stroke.partial.fromIndex`) and the trend-line config
 *  builder (for `fitUpTo`) — they must agree on the boundary. */
export function computeDashedFromIndex(
    r: TrendsResultLike,
    opts: { isStickiness?: boolean; incompletenessOffsetFromEnd?: number }
): number | undefined {
    const isActiveSeries = !r.compare || r.compare_label !== 'previous'
    const isInProgress =
        !opts.isStickiness && opts.incompletenessOffsetFromEnd !== undefined && opts.incompletenessOffsetFromEnd < 0
    if (!isInProgress || !isActiveSeries) {
        return undefined
    }
    return r.data.length + (opts.incompletenessOffsetFromEnd as number)
}

export function buildMainTrendsSeries<R extends TrendsResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildTrendsSeriesOpts<R, M>
): Series<M> {
    const dashedFromIndex = computeDashedFromIndex(r, opts)
    const yAxisId = opts.showMultipleYAxes && index > 0 ? `y${index}` : DEFAULT_Y_AXIS_ID
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta: M | undefined = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    return {
        key: String(r.id),
        label: r.label ?? '',
        data: r.data,
        color: opts.getColor(r, index),
        yAxisId,
        meta,
        fill: opts.display === ChartDisplayType.ActionsAreaGraph ? {} : undefined,
        stroke: dashedFromIndex !== undefined ? { partial: { fromIndex: dashedFromIndex } } : undefined,
        visibility: excluded ? { excluded: true } : undefined,
    }
}

export function buildTrendsSeries<R extends TrendsResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildMainTrendsSeries(r, index, opts))
}

export interface BuildDerivedConfigsOpts<R extends TrendsResultLike> {
    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showTrendLines?: boolean
    isStickiness?: boolean
    incompletenessOffsetFromEnd?: number
    getHidden?: (r: R) => boolean
}

export interface DerivedConfigs {
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    /** Map of comparison series key → its primary series key. See
     *  `TimeSeriesLineChartConfig.comparisonOf`. Only the presence of the key drives
     *  dimming today; the mapped value is reserved. */
    comparisonOf?: Record<string, string>
}

/** Translate a list of trends results + chart flags into the declarative derived-series
 *  config that `<TimeSeriesLineChart>` expects. Mirrors what the deleted
 *  `buildDerivedTrendsSeries` used to compute, but emits configs (not series) so the
 *  library owns the actual series construction. */
export function buildDerivedConfigs<R extends TrendsResultLike>(
    results: readonly R[],
    opts: BuildDerivedConfigsOpts<R>
): DerivedConfigs {
    const out: DerivedConfigs = {}
    if (!results.length) {
        return out
    }

    if (opts.showConfidenceIntervals) {
        const ci = (opts.confidenceLevel ?? 95) / 100
        out.confidenceIntervals = results.map((r) => {
            const [lower, upper] = ciRanges(r.data, ci)
            return { seriesKey: String(r.id), lower, upper }
        })
    }

    const includeMa = !!opts.showMovingAverage && opts.movingAverageIntervals !== undefined
    if (includeMa) {
        const window = opts.movingAverageIntervals as number
        out.movingAverage = results
            .filter((r) => r.data.length >= window)
            .map((r) => ({ seriesKey: String(r.id), window }))
    }

    if (opts.showTrendLines) {
        const trendLines: TrendLineConfig[] = []
        for (const r of results) {
            if (opts.getHidden?.(r)) {
                continue
            }
            const fitUpTo = computeDashedFromIndex(r, opts)
            trendLines.push({ seriesKey: String(r.id), kind: 'linear', fitUpTo })
            if (includeMa && r.data.length >= (opts.movingAverageIntervals as number)) {
                trendLines.push({
                    seriesKey: movingAverageKey(String(r.id)),
                    kind: 'linear',
                    label: `${r.label ?? ''} (Moving avg)`,
                })
            }
        }
        if (trendLines.length) {
            out.trendLines = trendLines
        }
    }

    const comparisonOf: Record<string, string> = {}
    for (const r of results) {
        if (r.compare && r.compare_label === 'previous') {
            const key = String(r.id)
            comparisonOf[key] = key
            // Derived MA series of the comparison should also render dimmed; same for
            // any future derived keys built from the comparison source.
            if (includeMa) {
                comparisonOf[movingAverageKey(key)] = key
            }
        }
    }
    if (Object.keys(comparisonOf).length) {
        out.comparisonOf = comparisonOf
    }

    return out
}
