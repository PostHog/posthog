import * as d3 from 'd3'

import type { ResolvedSeries } from '../../core/types'

export interface PieSlice<Meta = unknown> {
    /** Index into the *original* (pre-exclusion) series array. */
    seriesIndex: number
    series: ResolvedSeries<Meta>
    /** Absolute slice magnitude. Negative inputs are clamped to 0 — a pie can't render them. */
    value: number
    /** value / total (0 when total is 0). */
    fraction: number
    /** Radians, 12 o'clock = 0, increasing clockwise (d3.pie convention). */
    startAngle: number
    endAngle: number
    /** Bisector angle — anchor for pop-out and on-slice labels. */
    centroidAngle: number
    color: string
}

export interface PieLayout<Meta = unknown> {
    slices: PieSlice<Meta>[]
    total: number
    cx: number
    cy: number
    /** Outer slice radius, *excluding* hover pop-out room. */
    outerRadius: number
    /** Inner radius (0 for pie, > 0 for donut). */
    innerRadius: number
    /** Radians gap between adjacent slices. */
    padAngle: number
}

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

    const pieGenerator = d3
        .pie<Indexed>()
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

/** Maps a cursor offset (dx, dy) from the chart center to an angle in radians, matching
 *  the d3.pie convention: 12 o'clock = 0, increasing clockwise, range [0, 2π). */
export function cursorOffsetToAngle(dx: number, dy: number): number {
    // 12 o'clock = (0, -1) → atan2(0, 1) = 0
    // 3 o'clock = (1, 0) → atan2(1, 0) = π/2
    // 6 o'clock = (0, 1) → atan2(0, -1) = π
    // 9 o'clock = (-1, 0) → atan2(-1, 0) = -π/2 → normalized to 3π/2
    let a = Math.atan2(dx, -dy)
    if (a < 0) {
        a += 2 * Math.PI
    }
    return a
}

export interface SliceAtOptions {
    /** Allowance beyond `outerRadius` so the popped-out slice still registers as hovered. */
    outerSlack?: number
}

/** Returns the index of the slice under the cursor, or -1.
 *  - Misses the donut inner hole (`r < innerRadius`).
 *  - Misses past the outer edge plus optional slack.
 *  - Treats `padAngle/2` of each slice's start/end as a gap (no hit).
 *  - Handles d3.pie's 12 o'clock wraparound (slice that crosses 0). */
export function sliceAt<Meta>(
    layout: PieLayout<Meta>,
    cursor: { x: number; y: number },
    { outerSlack = 0 }: SliceAtOptions = {}
): number {
    if (layout.slices.length === 0) {
        return -1
    }
    const dx = cursor.x - layout.cx
    const dy = cursor.y - layout.cy
    const r = Math.hypot(dx, dy)
    if (r < layout.innerRadius || r > layout.outerRadius + outerSlack) {
        return -1
    }
    const a = cursorOffsetToAngle(dx, dy)
    const halfPad = layout.padAngle / 2
    for (let i = 0; i < layout.slices.length; i++) {
        const s = layout.slices[i]
        let start = s.startAngle + halfPad
        let end = s.endAngle - halfPad
        if (start >= end) {
            continue
        }
        if (start < 0 || end > 2 * Math.PI) {
            // Wraparound — slice crosses 12 o'clock. Split into the [start, 2π) ∪ [0, end mod 2π) check.
            const sNorm = ((start % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)
            const eNorm = ((end % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)
            if (a >= sNorm || a < eNorm) {
                return i
            }
            continue
        }
        if (a >= start && a < end) {
            return i
        }
    }
    return -1
}
