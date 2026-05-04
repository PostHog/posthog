import { useMemo } from 'react'

import type { Series } from '../../../core/types'
import {
    applyComparisonDimming,
    buildConfidenceIntervalSeries,
    buildMovingAverageSeries,
    buildTrendLineSeries,
} from './derived-series'

export interface ConfidenceIntervalConfig {
    seriesKey: string
    lower: number[]
    upper: number[]
}

export interface MovingAverageConfig {
    seriesKey: string
    window: number
    label?: string
}

export interface TrendLineConfig {
    seriesKey: string
    kind: 'linear' | 'exponential'
    label?: string
}

export interface DerivedSeriesOptions {
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    /** Map of comparison series key → its primary series key. Comparison series render
     *  at reduced opacity so they read as subordinate to their primary. */
    comparisonOf?: Record<string, string>
}

/** Builds CI bands, moving averages, and trend lines from `source` and merges them
 *  with the source series in paint order: CI behind, then main, then MA, then trend
 *  lines on top (matches `LineChart.drawStatic` array iteration). Comparison-period
 *  dimming runs as a final pass. Returns the original `source` reference when no
 *  derived-series options are set. */
export function useDerivedSeries<Meta>(source: Series<Meta>[], options: DerivedSeriesOptions): Series<Meta>[] {
    const { confidenceIntervals, movingAverage, trendLines, comparisonOf } = options
    return useMemo(() => {
        const hasDerived =
            (confidenceIntervals && confidenceIntervals.length > 0) ||
            (movingAverage && movingAverage.length > 0) ||
            (trendLines && trendLines.length > 0)
        const hasComparisons = comparisonOf && Object.keys(comparisonOf).length > 0
        if (!hasDerived && !hasComparisons) {
            return source
        }

        const sourceByKey = new Map(source.map((s) => [s.key, s]))

        const ciSeries: Series<Meta>[] = []
        for (const ci of confidenceIntervals ?? []) {
            const found = sourceByKey.get(ci.seriesKey)
            if (!found) {
                continue
            }
            ciSeries.push(
                buildConfidenceIntervalSeries<Meta>({
                    seriesKey: found.key,
                    label: found.label,
                    baseColor: found.color,
                    lower: ci.lower,
                    upper: ci.upper,
                    yAxisId: found.yAxisId,
                    meta: found.meta,
                    excluded: found.visibility?.excluded,
                })
            )
        }

        const maSeries: Series<Meta>[] = []
        for (const ma of movingAverage ?? []) {
            const found = sourceByKey.get(ma.seriesKey)
            if (!found) {
                continue
            }
            maSeries.push(buildMovingAverageSeries<Meta>({ sourceSeries: found, window: ma.window, label: ma.label }))
        }

        const tlSeries: Series<Meta>[] = []
        for (const tl of trendLines ?? []) {
            const found = sourceByKey.get(tl.seriesKey)
            if (!found) {
                continue
            }
            tlSeries.push(buildTrendLineSeries<Meta>({ sourceSeries: found, kind: tl.kind, label: tl.label }))
        }

        return applyComparisonDimming([...ciSeries, ...source, ...maSeries, ...tlSeries], comparisonOf)
    }, [source, confidenceIntervals, movingAverage, trendLines, comparisonOf])
}
