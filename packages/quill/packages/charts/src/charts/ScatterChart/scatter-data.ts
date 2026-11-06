import { extendValueRange } from '../../core/scales'
import type { SeriesValueRange } from '../../core/scales'
import type { Series } from '../../core/types'
import type { ScatterPointDatum, ScatterSeries } from './types'

/** A point in the chart's flat, x-sorted index space. Its position there is the `dataIndex` the base
 *  chart, the tooltip, and click payloads all speak in. */
export interface FlatScatterPoint<Meta = unknown> {
    seriesIndex: number
    seriesKey: string
    /** Index of this point within its own series' `points` array. */
    pointIndex: number
    x: number
    y: number
    label?: string
    radius?: number
    color?: string
    meta?: Meta
}

// Clamping a non-positive coordinate onto a log axis' edge would draw it at a value it lacks.
function isPlottable(value: number, logScale: boolean): boolean {
    return Number.isFinite(value) && (!logScale || value > 0)
}

/** Flattened into one list, sorted by x so the hit test can binary-search it. Unplottable points are
 *  dropped here, so everything downstream works off a drawable list. */
export function flattenScatterPoints<Meta>(
    series: ScatterSeries<Meta>[],
    options: { xLogScale?: boolean; yLogScale?: boolean } = {}
): FlatScatterPoint<Meta>[] {
    const { xLogScale = false, yLogScale = false } = options
    const flat: FlatScatterPoint<Meta>[] = []
    for (let seriesIndex = 0; seriesIndex < series.length; seriesIndex++) {
        const s = series[seriesIndex]
        for (let pointIndex = 0; pointIndex < s.points.length; pointIndex++) {
            const point = s.points[pointIndex]
            if (!isPlottable(point.x, xLogScale) || !isPlottable(point.y, yLogScale)) {
                continue
            }
            flat.push({ ...point, seriesIndex, seriesKey: s.key, pointIndex })
        }
    }
    return flat.sort((a, b) => a.x - b.x)
}

export function scatterValueRange(points: FlatScatterPoint[], axis: 'x' | 'y'): SeriesValueRange {
    const empty: SeriesValueRange = { min: Infinity, max: -Infinity, minPositive: Infinity, count: 0 }
    return extendValueRange(
        empty,
        points.map((point) => point[axis])
    )
}

/** One base-chart series per scatter series, carrying its own points' y values at their global
 *  indices and a gap (NaN) everywhere else. The gaps are what make the legend, the y-margin sizing,
 *  and the tooltip rows resolve to the one series holding the hovered point. */
export function toAdapterSeries(series: ScatterSeries<unknown>[], points: FlatScatterPoint[]): Series[] {
    const data = series.map(() => new Array<number>(points.length).fill(NaN))
    for (let i = 0; i < points.length; i++) {
        data[points[i].seriesIndex][i] = points[i].y
    }
    return series.map((s, i) => ({ key: s.key, label: s.label, data: data[i], color: s.color }))
}

export function toPointDatum<Meta>(
    point: FlatScatterPoint<Meta>,
    owner: ScatterSeries<Meta> | undefined,
    paletteColor: string
): ScatterPointDatum<Meta> {
    const { seriesKey, seriesIndex, pointIndex, ...rest } = point
    return {
        ...rest,
        seriesKey,
        seriesIndex,
        pointIndex,
        seriesLabel: owner?.label ?? '',
        color: point.color ?? owner?.color ?? paletteColor,
    }
}
