import { scaleLinear } from 'd3-scale'

import { X_LABEL_EDGE_PADDING } from '../../core/hooks/useChartMargins'
import type { D3YScale, SeriesValueRange } from '../../core/scales'
import { autoFormatterFor, extendValueRange, sanitizeFixedDomain } from '../../core/scales'
import type { ChartScales, ScatterMarkerShape } from '../../core/types'
import { measureLabelWidth } from '../../utils/text-measure'
import type { ScatterSeries } from './types'

/** One point lifted out of its series into the chart's flat, x-sorted index space. Its position in
 *  {@link flattenScatterPoints}' result is the point's *global index* — the id the base chart's
 *  label/series machinery, the tooltip, and click payloads all key off. */
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

/** A visible point resolved to canvas pixels and final marker style, ready to draw or hit-test. */
export interface ScatterPointPosition {
    /** Global index into the flattened point list. */
    index: number
    x: number
    y: number
    radius: number
    color: string
    shape: ScatterMarkerShape
}

/** Everything `createScales` resolves once per layout pass and the draw, hit-test, and axis-overlay
 *  code reads back. Rides in `ChartScales._private`, the chart-type-private slot, so each render
 *  carries its own self-consistent copy rather than a side-channel ref. */
export interface ScatterLayout {
    xScale: D3YScale
    yScale: D3YScale
    /** Visible, drawable points in ascending x-pixel order — the hit-test's search space. */
    positions: ScatterPointPosition[]
    xTicks: number[]
    /** Largest marker radius on the plot — the hit-test's pruning bound. */
    maxRadius: number
}

interface ScatterChartPrivate {
    __scatter: ScatterLayout
}

export function toScatterPrivate(layout: ScatterLayout): ScatterChartPrivate {
    return { __scatter: layout }
}

export function readScatterLayout(scales: ChartScales): ScatterLayout | undefined {
    return (scales._private as ScatterChartPrivate | undefined)?.__scatter
}

/** Ends of a scale interval as `[low, high]`, whichever way round it was declared — a y range runs
 *  bottom-to-top and a domain may descend. */
function bounds(interval: number[]): [number, number] {
    const first = interval[0]
    const last = interval[interval.length - 1]
    return first <= last ? [first, last] : [last, first]
}

/** Lowest and highest value a scale plots. Outside it a linear scale extrapolates and a clamped
 *  log scale piles points onto the plot edge, so a point outside these bounds isn't drawable. */
export function domainBounds(scale: D3YScale): [number, number] {
    return bounds(scale.domain())
}

/** Clamp a pixel into a scale's own range. A drag can end outside the plot, and inverting a pixel
 *  past the axis reports a value the user never brushed — on all-positive data, often a negative
 *  one. A log scale clamps on `invert` already; this makes the linear one agree. */
export function clampToRange(pixel: number, scale: D3YScale): number {
    const [low, high] = bounds(scale.range())
    return Math.min(Math.max(pixel, low), high)
}

/** A coordinate is plottable on a log axis only when it is strictly positive — `log(0)` is
 *  undefined and negatives have no place on the scale. Such points are dropped rather than
 *  clamped onto the axis edge, which would draw them at a value they don't have. */
function isPlottable(value: number, logScale: boolean): boolean {
    return Number.isFinite(value) && (!logScale || value > 0)
}

/** Flatten every series' points into one x-sorted list. Points that can't be placed on the
 *  configured scales (non-finite, or non-positive on a log axis) are dropped here, so everything
 *  downstream — scales, drawing, hit-testing, tooltips — works off a list where every entry is
 *  drawable. The sort is what lets {@link findNearestPointIndex} binary-search by x. */
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
    // Stable on ties (same x) so points keep their declaration order and the index space is
    // deterministic across renders.
    return flat.sort((a, b) => a.x - b.x)
}

/** Value range of one axis across the given points, in the shape `buildValueScale` consumes. */
export function scatterValueRange(points: FlatScatterPoint[], axis: 'x' | 'y'): SeriesValueRange {
    const empty: SeriesValueRange = { min: Infinity, max: -Infinity, minPositive: Infinity, count: 0 }
    return extendValueRange(
        empty,
        points.map((point) => point[axis])
    )
}

/** Half the widest x tick label, plus the shared edge padding — the gutter the plot needs beside a
 *  tick centered on its edge, or that label's outer half is cut by the wrapper's `overflow`.
 *
 *  `useChartMargins` sizes this from the category labels, which a continuous x axis has none of, so
 *  estimate it the way a horizontal bar chart's value axis does: nice ticks over the axis' range,
 *  measured with the axis' own formatter. The ticks that actually render depend on the plot width
 *  this reserve helps decide, so it is an estimate of the right magnitude, not the exact set. */
export function xLabelEdgeReserve(
    points: FlatScatterPoint[],
    domain: readonly [number, number] | undefined,
    tickFormatter: ((value: number) => string) | undefined
): number {
    let extent: [number, number]
    if (domain) {
        extent = sanitizeFixedDomain(domain)
    } else {
        const range = scatterValueRange(points, 'x')
        if (range.count === 0) {
            return 0
        }
        extent = [range.min, range.max]
    }
    const ticks = scaleLinear().domain(extent).nice(6).ticks(6)
    const format = tickFormatter ?? autoFormatterFor(ticks)
    let widest = 0
    for (const tick of ticks) {
        widest = Math.max(widest, measureLabelWidth(format(tick)))
    }
    return Math.ceil(widest / 2) + X_LABEL_EDGE_PADDING
}

/** Global index of the marker nearest the cursor, or -1 when none is within `slop` px of its edge.
 *
 *  A scatter chart can't hit-test on x alone the way a line or bar chart does: points stack at the
 *  same x, and most of the plot is empty space where the honest answer is "nothing here" rather
 *  than "the nearest column". Markers are ranked by distance to their *edge*, so a large marker
 *  the cursor sits inside beats a small one whose center happens to be a pixel closer.
 *
 *  `positions` must be x-sorted, which lets this binary-search to the cursor's x and sweep outward
 *  only while the x gap alone could still win — so a dense cloud costs a handful of comparisons
 *  rather than a full scan. `maxRadius` bounds how much a marker's size can offset that gap. */
export function findNearestPointIndex(
    positions: ScatterPointPosition[],
    cursorX: number,
    cursorY: number,
    slop: number,
    maxRadius: number
): number {
    let lo = 0
    let hi = positions.length
    while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (positions[mid].x < cursorX) {
            lo = mid + 1
        } else {
            hi = mid
        }
    }

    let best = -1
    let bestScore = slop
    const scoreAt = (i: number, dx: number): void => {
        const score = Math.hypot(dx, positions[i].y - cursorY) - positions[i].radius
        if (score < bestScore) {
            bestScore = score
            best = positions[i].index
        }
    }
    for (let i = lo; i < positions.length; i++) {
        const dx = positions[i].x - cursorX
        if (dx - maxRadius > bestScore) {
            break
        }
        scoreAt(i, dx)
    }
    for (let i = lo - 1; i >= 0; i--) {
        const dx = cursorX - positions[i].x
        if (dx - maxRadius > bestScore) {
            break
        }
        scoreAt(i, dx)
    }
    return best
}
