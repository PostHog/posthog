import { useMemo } from 'react'

import type { Series } from '../../../core/types'
import { buildConfidenceIntervalSeries, buildMovingAverageSeries } from './derived-series'

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

export interface DerivedSeriesOptions {
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
}

/** Builds CI bands and moving averages from `source` and merges them with the source
 *  series in paint order: CI behind, then main, then MA on top (matches
 *  `LineChart.drawStatic` array iteration). Returns the original `source` reference
 *  when no derived-series options are set. */
export function useDerivedSeries<Meta>(source: Series<Meta>[], options: DerivedSeriesOptions): Series<Meta>[] {
    const { confidenceIntervals, movingAverage } = options
    // Reduce each config to a primitive signature so callers passing inline configs
    // (`config={{ movingAverage: [...] }}`) don't reallocate the dep refs on every render
    // and miss the cache. CI's lower/upper data arrays aren't included — we assume the
    // caller hands us stable references when the underlying numbers haven't changed.
    const ciSignature = ciSig(confidenceIntervals)
    const maSignature = maSig(movingAverage)
    return useMemo(() => {
        const hasDerived =
            (confidenceIntervals && confidenceIntervals.length > 0) || (movingAverage && movingAverage.length > 0)
        if (!hasDerived) {
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

        return [...ciSeries, ...source, ...maSeries]
        // The signatures above stand in for the two reference-typed config inputs; the
        // raw refs are intentionally absent so inline-config callers don't bust the cache.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [source, ciSignature, maSignature])
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
