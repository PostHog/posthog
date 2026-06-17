import { pie } from 'd3-shape'

import type { PieLayout, PieSlice } from '../../core/radial-layout'
import type { ResolvedSeries } from '../../core/types'

export { cursorOffsetToAngle, sliceAt } from '../../core/radial-layout'
export type { PieLayout, PieSlice, SliceAtOptions } from '../../core/radial-layout'

export interface PlotBox {
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

export interface ComputePieLayoutOptions<Meta = unknown> {
    series: ResolvedSeries<Meta>[]
    dimensions: PlotBox
    /** Magnitude resolver. Defaults to sum of finite, positive entries in `series.data`. */
    sliceValue?: (series: ResolvedSeries<Meta>) => number
    /** 0 = pie, 0.5 = donut. Clamped to [0, 0.95]. */
    innerRadiusRatio?: number
    /** Radians gap between slices. Defaults to 0. */
    padAngle?: number
    /** Sort comparator on slice magnitudes, or `null` to preserve input order. Defaults to `null`. */
    sort?: ((a: number, b: number) => number) | null
    /** Outer-radius scale factor — pulls the outer edge in to leave room for hover pop-out
     *  and labels. Defaults to 0.92. */
    radiusPadding?: number
}

export function defaultSliceValue<Meta>(s: ResolvedSeries<Meta>): number {
    // Naive sum — `computePieLayout` clamps the result to 0 for negative totals. Keep this
    // close to "sum(series.data)" so a custom `sliceValue` that wants a different aggregation
    // (e.g. last point only, average) replaces the whole resolver rather than fighting a
    // pre-clamp here.
    let sum = 0
    for (const v of s.data) {
        if (typeof v === 'number' && Number.isFinite(v)) {
            sum += v
        }
    }
    return sum
}

export function computePieLayout<Meta = unknown>(opts: ComputePieLayoutOptions<Meta>): PieLayout<Meta> {
    const {
        series,
        dimensions,
        sliceValue = defaultSliceValue,
        innerRadiusRatio = 0,
        padAngle = 0,
        sort = null,
        radiusPadding = 0.92,
    } = opts

    const cx = dimensions.plotLeft + dimensions.plotWidth / 2
    const cy = dimensions.plotTop + dimensions.plotHeight / 2
    const shorterSide = Math.min(dimensions.plotWidth, dimensions.plotHeight)
    const outerRadius = Math.max(0, (shorterSide / 2) * radiusPadding)
    const clampedInnerRatio = Math.max(0, Math.min(innerRadiusRatio, 0.95))
    const innerRadius = clampedInnerRatio * outerRadius

    // Index *before* filtering so click handlers can recover the original series position.
    type Indexed = { series: ResolvedSeries<Meta>; value: number; seriesIndex: number }
    const indexed: Indexed[] = []
    for (let i = 0; i < series.length; i++) {
        const s = series[i]
        if (s.visibility?.excluded) {
            continue
        }
        const raw = sliceValue(s)
        const value = typeof raw === 'number' && Number.isFinite(raw) && raw > 0 ? raw : 0
        indexed.push({ series: s, value, seriesIndex: i })
    }

    let total = 0
    for (const i of indexed) {
        total += i.value
    }

    if (total <= 0 || indexed.length === 0 || outerRadius <= 0) {
        return { slices: [], total: 0, cx, cy, outerRadius, innerRadius, padAngle }
    }

    const pieGenerator = pie<Indexed>()
        .value((d) => d.value)
        .padAngle(padAngle)
    if (sort === null) {
        pieGenerator.sort(null)
    } else {
        pieGenerator.sort((a, b) => sort(a.value, b.value))
    }
    const arcs = pieGenerator(indexed)

    const slices: PieSlice<Meta>[] = arcs.map((arc) => {
        const centroidAngle = (arc.startAngle + arc.endAngle) / 2
        return {
            seriesIndex: arc.data.seriesIndex,
            series: arc.data.series,
            value: arc.data.value,
            fraction: arc.data.value / total,
            startAngle: arc.startAngle,
            endAngle: arc.endAngle,
            centroidAngle,
            color: arc.data.series.color,
        }
    })

    return { slices, total, cx, cy, outerRadius, innerRadius, padAngle }
}
