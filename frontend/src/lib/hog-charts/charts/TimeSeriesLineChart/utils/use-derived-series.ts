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
    /** Restrict the regression fit to indices `[0, fitUpTo)`; trend is still extrapolated
     *  across the full range. Use to exclude an in-progress tail so the partial bucket
     *  doesn't drag the slope. */
    fitUpTo?: number
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
    // Reduce each config to a primitive signature so callers passing inline configs
    // (`config={{ trendLines: [...] }}`) don't reallocate the dep refs on every render
    // and miss the cache. CI's lower/upper data arrays aren't included — we assume the
    // caller hands us stable references when the underlying numbers haven't changed.
    const ciSignature = ciSig(confidenceIntervals)
    const maSignature = maSig(movingAverage)
    const tlSignature = tlSig(trendLines)
    const cmpSignature = cmpSig(comparisonOf)
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

        // Trend lines may reference moving-average series too (e.g. trends renders both a
        // raw trendline and a trendline of the MA), so fold MA keys into the lookup —
        // but only clone the source map when there are MA entries to add.
        let trendLineSourceByKey = sourceByKey
        if (maSeries.length > 0) {
            trendLineSourceByKey = new Map(sourceByKey)
            for (const ma of maSeries) {
                trendLineSourceByKey.set(ma.key, ma)
            }
        }
        const tlSeries: Series<Meta>[] = []
        for (const tl of trendLines ?? []) {
            const found = trendLineSourceByKey.get(tl.seriesKey)
            if (!found) {
                continue
            }
            tlSeries.push(
                buildTrendLineSeries<Meta>({
                    sourceSeries: found,
                    kind: tl.kind,
                    label: tl.label,
                    fitUpTo: tl.fitUpTo,
                })
            )
        }

        return applyComparisonDimming([...ciSeries, ...source, ...maSeries, ...tlSeries], comparisonOf)
        // The signatures above stand in for the four reference-typed config inputs; the
        // raw refs are intentionally absent so inline-config callers don't bust the cache.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [source, ciSignature, maSignature, tlSignature, cmpSignature])
}

function ciSig(ci: ConfidenceIntervalConfig[] | undefined): string {
    if (!ci?.length) {
        return ''
    }
    // Identity of CI inputs: which series, and the lower/upper array refs.
    // We avoid serialising the data arrays — array reference equality is the
    // caller's contract for "values haven't changed."
    return ci.map((c) => `${c.seriesKey}|${refKey(c.lower)}|${refKey(c.upper)}`).join(';')
}

function maSig(ma: MovingAverageConfig[] | undefined): string {
    if (!ma?.length) {
        return ''
    }
    return ma.map((m) => `${m.seriesKey}|${m.window}|${m.label ?? ''}`).join(';')
}

function tlSig(tl: TrendLineConfig[] | undefined): string {
    if (!tl?.length) {
        return ''
    }
    return tl.map((t) => `${t.seriesKey}|${t.kind}|${t.label ?? ''}|${t.fitUpTo ?? ''}`).join(';')
}

function cmpSig(cmp: Record<string, string> | undefined): string {
    if (!cmp) {
        return ''
    }
    return Object.entries(cmp)
        .map(([k, v]) => `${k}=${v}`)
        .sort()
        .join(';')
}

const refIds = new WeakMap<object, number>()
let nextRefId = 1
function refKey(arr: number[]): number {
    let id = refIds.get(arr)
    if (id === undefined) {
        id = nextRefId++
        refIds.set(arr, id)
    }
    return id
}
