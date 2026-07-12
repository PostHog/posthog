import { type ScaleLinear, type ScaleLogarithmic } from 'd3-scale'

import { barColorAt, mixColors } from './color-utils'
import { yTickCountForHeight } from './scales'
import type {
    BarFillStyle,
    BoxRect,
    ChartDimensions,
    ChartDrawArgs,
    ChartTheme,
    DrawHoverResult,
    ResolvedSeries,
} from './types'

export interface DrawContext {
    ctx: CanvasRenderingContext2D
    dimensions: ChartDimensions
    xScale: (label: string) => number | undefined
    yScale: ScaleLinear<number, number> | ScaleLogarithmic<number, number>
    labels: string[]
    /** Smooth the line/area with monotone-cubic interpolation instead of straight segments. */
    smooth?: boolean
    /** Largest drawable y (px) for line/area strokes. Charts drawing an x-axis line pass the
     *  baseline minus half their stroke width, so a baseline-hugging stroke rests exactly on the
     *  axis line instead of straddling it. Pure draw-time clamp — scales and ticks are untouched. */
    yFloor?: number
}

/** Stroke width of series lines. Half of it is the stroke's overhang past a point, which the
 *  `yFloor`/left-clip callers use to keep strokes flush against drawn axis lines. */
export const LINE_STROKE_WIDTH = 2

export function drawLine(drawCtx: DrawContext, series: ResolvedSeries, yValues?: number[]): void {
    const data = yValues ?? series.data
    if (data.length === 0) {
        return
    }

    const { ctx } = drawCtx
    ctx.strokeStyle = series.color
    ctx.lineWidth = LINE_STROKE_WIDTH
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    if (drawFractionalTailDash(drawCtx, series, data)) {
        ctx.setLineDash([])
        return
    }

    for (const { start, end, pattern } of planLineStrokes(series, data.length)) {
        ctx.beginPath()
        ctx.setLineDash(pattern)
        tracePath(drawCtx, data, start, end)
        ctx.stroke()
    }
    ctx.setLineDash([])
}

/** Dashes only the tail of the final segment, split at `stroke.partial.fromFraction`. Draws the line
 *  solid up to the split pixel, then dashed to the last point. Returns false (no-op) when the option
 *  is unset or the final segment's endpoints aren't both drawable, so the caller falls back to the
 *  index-based stroke plan. */
function drawFractionalTailDash(drawCtx: DrawContext, series: ResolvedSeries, data: number[]): boolean {
    const fraction = series.stroke?.partial?.fromFraction
    if (fraction == null || data.length < 2) {
        return false
    }
    const { ctx, xScale, yScale, labels, yFloor, smooth } = drawCtx
    const last = data.length - 1
    const x0 = xScale(labels[last - 1])
    const rawY0 = yScale(data[last - 1])
    const x1 = xScale(labels[last])
    const rawY1 = yScale(data[last])
    if (x0 == null || x1 == null || !isFinite(rawY0) || !isFinite(rawY1)) {
        return false
    }
    const y0 = yFloor != null ? Math.min(rawY0, yFloor) : rawY0
    const y1 = yFloor != null ? Math.min(rawY1, yFloor) : rawY1

    const f = Math.max(0, Math.min(1, fraction))

    if (smooth) {
        drawSmoothFractionalTail(drawCtx, series, data, f)
        return true
    }

    const splitX = x0 + (x1 - x0) * f
    const splitY = y0 + (y1 - y0) * f

    // Solid: every leading point through to the split pixel inside the final segment.
    ctx.beginPath()
    ctx.setLineDash(series.stroke?.pattern ?? [])
    tracePath(drawCtx, data, 0, last - 1)
    ctx.lineTo(splitX, splitY)
    ctx.stroke()

    // Dashed: the split pixel out to the final point.
    ctx.beginPath()
    ctx.setLineDash(series.stroke?.partial?.pattern ?? [10, 10])
    ctx.moveTo(splitX, splitY)
    ctx.lineTo(x1, y1)
    ctx.stroke()
    return true
}

/** Two cubic bezier halves from splitting one segment at parameter `t` (de Casteljau). */
interface SplitCubic {
    /** Split point — end of the first half, start of the second. */
    x: number
    y: number
    firstCp1x: number
    firstCp1y: number
    firstCp2x: number
    firstCp2y: number
    secondCp1x: number
    secondCp1y: number
    secondCp2x: number
    secondCp2y: number
}

/** Split the cubic bezier `p0 → (seg.cp1, seg.cp2) → p3` at parameter `t` into two halves that
 *  together trace the identical curve (de Casteljau subdivision). */
function splitCubicBezier(p0: Point, seg: CurveSegment, p3: Point, t: number): SplitCubic {
    const lerp = (a: number, b: number): number => a + (b - a) * t
    const p01x = lerp(p0.x, seg.cp1x)
    const p01y = lerp(p0.y, seg.cp1y)
    const p12x = lerp(seg.cp1x, seg.cp2x)
    const p12y = lerp(seg.cp1y, seg.cp2y)
    const p23x = lerp(seg.cp2x, p3.x)
    const p23y = lerp(seg.cp2y, p3.y)
    const p012x = lerp(p01x, p12x)
    const p012y = lerp(p01y, p12y)
    const p123x = lerp(p12x, p23x)
    const p123y = lerp(p12y, p23y)
    return {
        x: lerp(p012x, p123x),
        y: lerp(p012y, p123y),
        firstCp1x: p01x,
        firstCp1y: p01y,
        firstCp2x: p012x,
        firstCp2y: p012y,
        secondCp1x: p123x,
        secondCp1y: p123y,
        secondCp2x: p23x,
        secondCp2y: p23y,
    }
}

/** The `smooth` branch of {@link drawFractionalTailDash}: draws the monotone curve solid up to the
 *  split point and dashed from there to the last point. `f` is taken as the bezier parameter of the
 *  final segment (splitting the same curve the rest of the line follows), so the dashed tail stays
 *  on the curve instead of reverting to a straight chord. Leading gap-separated runs draw solid. */
function drawSmoothFractionalTail(drawCtx: DrawContext, series: ResolvedSeries, data: number[], f: number): void {
    const { ctx } = drawCtx
    const runs = collectSmoothRuns(drawCtx, data, 0, data.length - 1)
    // The caller's guard ensures the last two indices are finite and adjacent, so the final run
    // ends at the last point with at least two points — a splittable final segment.
    const tail = runs[runs.length - 1]
    const segs = monotoneSegments(tail)
    const lastSeg = segs[segs.length - 1]
    const split = splitCubicBezier(tail[tail.length - 2], lastSeg, tail[tail.length - 1], f)

    // Solid: every leading run in full, then the final run up to the split point on its last segment.
    ctx.beginPath()
    ctx.setLineDash(series.stroke?.pattern ?? [])
    for (let r = 0; r < runs.length - 1; r++) {
        ctx.moveTo(runs[r][0].x, runs[r][0].y)
        if (runs[r].length > 1) {
            curveForward(ctx, runs[r])
        }
    }
    ctx.moveTo(tail[0].x, tail[0].y)
    for (let i = 0; i < segs.length - 1; i++) {
        ctx.bezierCurveTo(segs[i].cp1x, segs[i].cp1y, segs[i].cp2x, segs[i].cp2y, tail[i + 1].x, tail[i + 1].y)
    }
    ctx.bezierCurveTo(split.firstCp1x, split.firstCp1y, split.firstCp2x, split.firstCp2y, split.x, split.y)
    ctx.stroke()

    // Dashed: the split point out to the final point, along the same curve.
    ctx.beginPath()
    ctx.setLineDash(series.stroke?.partial?.pattern ?? [10, 10])
    ctx.moveTo(split.x, split.y)
    const end = tail[tail.length - 1]
    ctx.bezierCurveTo(split.secondCp1x, split.secondCp1y, split.secondCp2x, split.secondCp2y, end.x, end.y)
    ctx.stroke()
}

/** One contiguous stroke: indices [start, end] inclusive, rendered with `pattern`. */
interface Stroke {
    start: number
    end: number
    pattern: number[]
}

/**
 * Splits the line into strokes based on `stroke.partial.fromIndex`/`stroke.partial.toIndex`.
 * Each entry is a contiguous index range drawn with a single dash pattern; adjacent strokes
 * share their boundary index so the visual seam between them is invisible.
 */
function planLineStrokes(series: ResolvedSeries, length: number): Stroke[] {
    const basePattern = series.stroke?.pattern ?? []
    const partialPattern = series.stroke?.partial?.pattern ?? [10, 10]
    const from = resolvePartialIndex(series.stroke?.partial?.fromIndex, length)
    const to = resolvePartialIndex(series.stroke?.partial?.toIndex, length)

    // No partial dashing — one stroke covering the whole line.
    if (from === null && to === null) {
        return [{ start: 0, end: length - 1, pattern: basePattern }]
    }

    // Dashed region(s) cover the whole line — from the start, through the end, or meeting in the middle.
    const wholeLineDashed = from === 0 || to === length - 1 || (from !== null && to !== null && to >= from - 1)
    if (wholeLineDashed) {
        return [{ start: 0, end: length - 1, pattern: partialPattern }]
    }

    // Up to three strokes: dashed leading → solid middle → dashed trailing.
    const strokes: Stroke[] = []
    if (to !== null) {
        strokes.push({ start: 0, end: to, pattern: partialPattern })
    }
    const solidStart = to ?? 0
    const solidEnd = from !== null ? from - 1 : length - 1
    if (solidStart < solidEnd) {
        strokes.push({ start: solidStart, end: solidEnd, pattern: basePattern })
    }
    if (from !== null) {
        strokes.push({ start: from - 1, end: length - 1, pattern: partialPattern })
    }
    return strokes
}

/** Walks data from [start, end] inclusive. Emits straight segments streamed point by point, or
 *  monotone-cubic curves when `drawCtx.smooth` is set (the smooth branch buffers each subpath's
 *  points since the tangents need the whole run). NaN/out-of-domain points break the line into
 *  separate subpaths. Caller owns beginPath/stroke. */
function tracePath(drawCtx: DrawContext, data: number[], start: number, end: number): void {
    const { ctx, xScale, yScale, labels, smooth, yFloor } = drawCtx
    if (smooth) {
        traceSmoothPath(drawCtx, data, start, end)
        return
    }
    let started = false
    for (let i = start; i <= end; i++) {
        const x = xScale(labels[i])
        const rawY = yScale(data[i])
        if (x == null || !isFinite(rawY)) {
            // Reset so the next valid point starts a fresh subpath rather than
            // connecting straight across the NaN gap.
            started = false
            continue
        }
        const y = yFloor != null ? Math.min(rawY, yFloor) : rawY
        if (!started) {
            ctx.moveTo(x, y)
            started = true
        } else {
            ctx.lineTo(x, y)
        }
    }
}

interface Point {
    x: number
    y: number
}

/** Collects the drawable points of [start, end] into gap-delimited runs — a new run starts after
 *  every NaN/out-of-domain point, so each run is a contiguous subpath. `yFloor` clamps each point. */
function collectSmoothRuns(drawCtx: DrawContext, data: number[], start: number, end: number): Point[][] {
    const { xScale, yScale, labels, yFloor } = drawCtx
    const runs: Point[][] = []
    let run: Point[] = []
    for (let i = start; i <= end; i++) {
        const x = xScale(labels[i])
        const y = yScale(data[i])
        if (x == null || !isFinite(y)) {
            if (run.length > 0) {
                runs.push(run)
                run = []
            }
            continue
        }
        run.push({ x, y: yFloor != null ? Math.min(y, yFloor) : y })
    }
    if (run.length > 0) {
        runs.push(run)
    }
    return runs
}

/** The `smooth` branch of {@link tracePath}: emits monotone-cubic bezier segments through each
 *  gap-delimited subpath. */
function traceSmoothPath(drawCtx: DrawContext, data: number[], start: number, end: number): void {
    const { ctx } = drawCtx
    for (const run of collectSmoothRuns(drawCtx, data, start, end)) {
        ctx.moveTo(run[0].x, run[0].y)
        if (run.length > 1) {
            curveForward(ctx, run)
        }
    }
}

/** Monotone-cubic (Fritsch–Carlson) tangents for points with strictly increasing x. Matches d3's
 *  `curveMonotoneX`: preserves monotonicity between points, so the curve never overshoots the data
 *  (no spurious wiggles or dips past a peak/trough). Hand-rolled rather than d3-shape because the
 *  shortened `SMOOTH_ARM` below isn't expressible with d3's fixed 1/3 arm. */
function monotoneTangents(pts: Point[]): number[] {
    const n = pts.length
    const h: number[] = new Array(n - 1)
    const s: number[] = new Array(n - 1)
    for (let i = 0; i < n - 1; i++) {
        h[i] = pts[i + 1].x - pts[i].x
        s[i] = h[i] !== 0 ? (pts[i + 1].y - pts[i].y) / h[i] : 0
    }
    const m: number[] = new Array(n)
    if (n === 2) {
        m[0] = s[0]
        m[1] = s[0]
        return m
    }
    for (let i = 1; i < n - 1; i++) {
        const s0 = s[i - 1]
        const s1 = s[i]
        if (s0 * s1 <= 0) {
            m[i] = 0
        } else {
            const p = (s0 * h[i] + s1 * h[i - 1]) / (h[i - 1] + h[i])
            m[i] = (Math.sign(s0) + Math.sign(s1)) * Math.min(Math.abs(s0), Math.abs(s1), 0.5 * Math.abs(p))
        }
    }
    m[0] = (3 * s[0] - m[1]) / 2
    m[n - 1] = (3 * s[n - 2] - m[n - 2]) / 2
    return m
}

interface CurveSegment {
    cp1x: number
    cp1y: number
    cp2x: number
    cp2y: number
}

// Control-arm length as a fraction of the segment width. 1/3 is the standard monotone-cubic arm
// (full curve); shortening it pulls the curve closer to the straight chord between points for a
// gentler bend. Crucially this keeps the *same* tangent direction at each point, so adjacent
// segments still meet smoothly there — the data points stay rounded, only the mid-segment bow shrinks.
const SMOOTH_ARM = 1 / 4

function monotoneSegments(pts: Point[]): CurveSegment[] {
    const m = monotoneTangents(pts)
    const segs: CurveSegment[] = []
    for (let i = 0; i < pts.length - 1; i++) {
        const arm = (pts[i + 1].x - pts[i].x) * SMOOTH_ARM
        segs.push({
            cp1x: pts[i].x + arm,
            cp1y: pts[i].y + m[i] * arm,
            cp2x: pts[i + 1].x - arm,
            cp2y: pts[i + 1].y - m[i + 1] * arm,
        })
    }
    return segs
}

/** Emit monotone bezier segments from the first point forward. Assumes the current path point is
 *  already at `pts[0]`. */
function curveForward(ctx: CanvasRenderingContext2D, pts: Point[]): void {
    const segs = monotoneSegments(pts)
    for (let i = 0; i < segs.length; i++) {
        ctx.bezierCurveTo(segs[i].cp1x, segs[i].cp1y, segs[i].cp2x, segs[i].cp2y, pts[i + 1].x, pts[i + 1].y)
    }
}

/** Emit the same monotone curve traversed last→first (control points swapped). Assumes the current
 *  path point is already at `pts[n-1]`. Used for an area's bottom edge. */
function curveReverse(ctx: CanvasRenderingContext2D, pts: Point[]): void {
    const segs = monotoneSegments(pts)
    for (let i = segs.length - 1; i >= 0; i--) {
        ctx.bezierCurveTo(segs[i].cp2x, segs[i].cp2y, segs[i].cp1x, segs[i].cp1y, pts[i].x, pts[i].y)
    }
}

/** Returns null when unset; otherwise rounds and clamps into [0, length-1]. */
function resolvePartialIndex(idx: number | undefined, length: number): number | null {
    if (idx == null || length === 0) {
        return null
    }
    const rounded = Math.round(idx)
    return Math.max(0, Math.min(length - 1, rounded))
}

const hatchPatternCache = new Map<string, CanvasPattern>()

function getHatchPattern(ctx: CanvasRenderingContext2D, color: string): CanvasPattern | string {
    const cached = hatchPatternCache.get(color)
    if (cached) {
        return cached
    }
    const size = 14
    const patCanvas = document.createElement('canvas')
    patCanvas.width = size
    patCanvas.height = size
    const patCtx = patCanvas.getContext('2d')
    if (!patCtx) {
        return color
    }
    patCtx.strokeStyle = color
    patCtx.lineWidth = 4
    patCtx.beginPath()
    patCtx.moveTo(0, size)
    patCtx.lineTo(size, 0)
    patCtx.stroke()
    patCtx.beginPath()
    patCtx.moveTo(-size / 2, size / 2)
    patCtx.lineTo(size / 2, -size / 2)
    patCtx.stroke()
    patCtx.beginPath()
    patCtx.moveTo(size / 2, size + size / 2)
    patCtx.lineTo(size + size / 2, size / 2)
    patCtx.stroke()
    const pattern = ctx.createPattern(patCanvas, 'repeat')
    if (pattern) {
        hatchPatternCache.set(color, pattern)
        return pattern
    }
    return color
}

interface AreaPoint {
    x: number
    y: number
    dataIndex: number
}

export function drawArea(
    drawCtx: DrawContext,
    series: ResolvedSeries,
    yValues?: number[],
    bottomValues?: number[]
): void {
    const { ctx, xScale, yScale, labels, dimensions, smooth, yFloor } = drawCtx
    const data = yValues ?? series.data
    const opacity = series.fill?.opacity ?? 0.5
    const baseline = dimensions.plotTop + dimensions.plotHeight
    const dashedFrom = resolvePartialIndex(series.stroke?.partial?.fromIndex, data.length)
    const dashedTo = resolvePartialIndex(series.stroke?.partial?.toIndex, data.length)

    const segments: { top: AreaPoint[]; bottom: AreaPoint[] }[] = []
    let currentTop: AreaPoint[] = []
    let currentBottom: AreaPoint[] = []
    const breakSegment = (): void => {
        if (currentTop.length > 0) {
            segments.push({ top: currentTop, bottom: currentBottom })
            currentTop = []
            currentBottom = []
        }
    }
    for (let i = 0; i < data.length; i++) {
        const x = xScale(labels[i])
        const rawTop = yScale(data[i])
        if (x == null || !isFinite(rawTop)) {
            breakSegment()
            continue
        }
        // Clamped like the line stroke so the area's top edge stays under it; the bottom edge
        // still fills down to the baseline, keeping the area anchored to the axis.
        const yTop = yFloor != null ? Math.min(rawTop, yFloor) : rawTop
        if (bottomValues) {
            const rawBottom = bottomValues[i]
            const yBot = rawBottom == null ? NaN : yScale(rawBottom)
            if (!isFinite(yBot)) {
                breakSegment()
                continue
            }
            currentTop.push({ x, y: yTop, dataIndex: i })
            currentBottom.push({ x, y: yBot, dataIndex: i })
        } else {
            currentTop.push({ x, y: yTop, dataIndex: i })
            currentBottom.push({ x, y: baseline, dataIndex: i })
        }
    }
    breakSegment()

    ctx.globalAlpha = opacity

    // A gradient fill always paints the whole area; partial dashing then only affects the stroke
    // (drawLine), so the fade stays intact under an in-progress dashed tail instead of flipping to
    // the solid + hatch treatment below (which non-gradient area charts still use).
    const useGradient = series.fill?.gradient && !bottomValues
    let gradient: CanvasGradient | null = null
    if (useGradient) {
        gradient = ctx.createLinearGradient(0, dimensions.plotTop, 0, baseline)
        gradient.addColorStop(0, series.color)
        gradient.addColorStop(1, 'transparent')
    }

    for (const { top, bottom } of segments) {
        if (top.length < 2) {
            continue
        }

        if (useGradient || (dashedFrom === null && dashedTo === null)) {
            ctx.fillStyle = gradient ?? series.color
            fillAreaPath(ctx, top, bottom, smooth)
            continue
        }

        // First index in this segment that is part of the trailing dashed range (>= dashedFrom).
        const fromSplit = dashedFrom === null ? -1 : top.findIndex((p) => p.dataIndex >= dashedFrom)
        // First index in this segment that is past the leading dashed range (> dashedTo).
        const toSplit = dashedTo === null ? -1 : top.findIndex((p) => p.dataIndex > dashedTo)
        const wholeSegmentLeading = dashedTo !== null && toSplit === -1
        const wholeSegmentTrailing = dashedFrom !== null && fromSplit === 0
        const hatch = getHatchPattern(ctx, series.color)

        if (wholeSegmentLeading || wholeSegmentTrailing) {
            ctx.fillStyle = hatch
            fillAreaPath(ctx, top, bottom, smooth)
            continue
        }

        if (dashedTo !== null && toSplit > 0) {
            const leadingEnd = Math.min(top.length, toSplit + 1)
            ctx.fillStyle = hatch
            fillAreaPath(ctx, top.slice(0, leadingEnd), bottom.slice(0, leadingEnd), smooth)
        }

        const solidStart = toSplit === -1 ? 0 : toSplit
        const solidEnd = fromSplit === -1 ? top.length : fromSplit

        // Solid stops exactly where the trailing hatch begins (its `hatchStart = fromSplit - 1`), sharing
        // that one boundary point — no overlap. Otherwise the solid fill bleeds under the first dashed
        // segment and the shaded region stops a step past where the line turns dashed.
        if (solidEnd - solidStart >= 2) {
            ctx.fillStyle = series.color
            fillAreaPath(ctx, top.slice(solidStart, solidEnd), bottom.slice(solidStart, solidEnd), smooth)
        }

        if (dashedFrom !== null && fromSplit > 0) {
            const hatchStart = Math.max(0, fromSplit - 1)
            ctx.fillStyle = hatch
            fillAreaPath(ctx, top.slice(hatchStart), bottom.slice(hatchStart), smooth)
        }
    }

    ctx.globalAlpha = 1
}

function fillAreaPath(ctx: CanvasRenderingContext2D, top: Point[], bottom: Point[], smooth?: boolean): void {
    ctx.beginPath()
    ctx.moveTo(top[0].x, top[0].y)
    if (smooth && top.length > 1) {
        curveForward(ctx, top)
    } else {
        for (let i = 1; i < top.length; i++) {
            ctx.lineTo(top[i].x, top[i].y)
        }
    }
    ctx.lineTo(bottom[bottom.length - 1].x, bottom[bottom.length - 1].y)
    if (smooth && bottom.length > 1) {
        curveReverse(ctx, bottom)
    } else {
        for (let i = bottom.length - 2; i >= 0; i--) {
            ctx.lineTo(bottom[i].x, bottom[i].y)
        }
    }
    ctx.closePath()
    ctx.fill()
}

export function drawPoints(drawCtx: DrawContext, series: ResolvedSeries, yValues?: number[]): void {
    const { ctx, xScale, yScale, labels } = drawCtx
    const data = yValues ?? series.data
    const radius = series.points?.radius ?? 0

    if (radius <= 0) {
        return
    }

    ctx.fillStyle = series.color

    for (let i = 0; i < data.length; i++) {
        const x = xScale(labels[i])
        const y = yScale(data[i])
        if (x == null || !isFinite(y)) {
            continue
        }
        ctx.beginPath()
        ctx.arc(x, y, radius, 0, Math.PI * 2)
        ctx.fill()
    }
}

/** Snap a coordinate to the nearest half-pixel so a 1px stroke fills exactly one pixel row/column.
 *  Every axis-adjacent stroke — grid lines, axis baselines, tick marks — must share this rule, or
 *  they land one pixel apart and visibly misalign. */
function snapToPixel(coord: number): number {
    return Math.round(coord) + 0.5
}

/** The stroke color for axis lines and tick marks — separate from `axisColor` (tick-label text)
 *  so hosts can mute the lines without muting the labels. One place, so the precedence can't
 *  drift between call sites. */
export function resolveAxisLineColor(theme: ChartTheme): string | undefined {
    return theme.axisLineColor ?? theme.axisColor ?? theme.gridColor
}

export interface DrawAxesOptions {
    axisColor?: string
    /** Stroke the bottom (x) baseline. Default true. */
    xLine?: boolean
    /** Stroke the left (y) baseline. Default true. */
    yLine?: boolean
    /** Also stroke the right plot edge — for charts with a right-positioned y-axis. Gated on `yLine`. */
    rightAxis?: boolean
}

/** Draws just the L-shaped axis baselines — the left value axis and the bottom category axis —
 *  without any interior grid lines. For charts that want axis framing but a clean, grid-free plot. */
export function drawAxes(drawCtx: DrawContext, options: DrawAxesOptions = {}): void {
    const { ctx, dimensions } = drawCtx
    const { xLine = true, yLine = true } = options
    ctx.strokeStyle = options.axisColor ?? 'rgba(0, 0, 0, 0.15)'
    ctx.lineWidth = 1
    ctx.setLineDash([])
    // snapToPixel matches drawGrid's tick snapping, so the bottom baseline coincides exactly with a
    // zero-value grid line and with drawTickMarks' ticks.
    const axisX = snapToPixel(dimensions.plotLeft)
    const axisY = snapToPixel(dimensions.plotTop + dimensions.plotHeight)
    const rightX = snapToPixel(dimensions.plotLeft + dimensions.plotWidth)
    // Route the strokes through shared, snapped corners so the lines meet cleanly even when the
    // plot edges are fractional.
    if (yLine) {
        ctx.beginPath()
        ctx.moveTo(axisX, dimensions.plotTop)
        ctx.lineTo(axisX, axisY)
        ctx.stroke()
    }
    if (xLine) {
        ctx.beginPath()
        ctx.moveTo(axisX, axisY)
        ctx.lineTo(rightX, axisY)
        ctx.stroke()
    }
    if (yLine && options.rightAxis) {
        ctx.beginPath()
        ctx.moveTo(rightX, dimensions.plotTop)
        ctx.lineTo(rightX, axisY)
        ctx.stroke()
    }
}

/** Length (px) of an axis tick mark, measured outward from the plot edge. */
export const TICK_MARK_LENGTH = 4

/** Pixel positions for canvas tick marks: `xs` tick below the plot's bottom edge, `ys` tick outside
 *  the left or right plot edge (`offset` pushes stacked multi-axis gutters further outward). */
export interface TickMarkCoords {
    xs: number[]
    ys: { y: number; side: 'left' | 'right'; offset: number }[]
}

/** Draws short tick marks extending outward from the plot edges, one per visible axis label.
 *  Canvas-drawn with the same snapping as `drawAxes`/`drawGrid` so each tick continues its
 *  axis/grid line exactly — a DOM overlay can't guarantee that across subpixel rounding. */
export function drawTickMarks(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    coords: TickMarkCoords,
    color?: string
): void {
    ctx.strokeStyle = color ?? 'rgba(0, 0, 0, 0.15)'
    ctx.lineWidth = 1
    ctx.setLineDash([])
    const axisY = snapToPixel(dimensions.plotTop + dimensions.plotHeight)
    ctx.beginPath()
    for (const x of coords.xs) {
        const tickX = snapToPixel(x)
        ctx.moveTo(tickX, axisY)
        ctx.lineTo(tickX, axisY + TICK_MARK_LENGTH)
    }
    for (const { y, side, offset } of coords.ys) {
        const tickY = snapToPixel(y)
        if (side === 'left') {
            const edge = snapToPixel(dimensions.plotLeft - offset)
            ctx.moveTo(edge - TICK_MARK_LENGTH, tickY)
            ctx.lineTo(edge, tickY)
        } else {
            const edge = snapToPixel(dimensions.plotLeft + dimensions.plotWidth + offset)
            ctx.moveTo(edge, tickY)
            ctx.lineTo(edge + TICK_MARK_LENGTH, tickY)
        }
    }
    ctx.stroke()
}

export interface DrawGridOptions {
    gridColor?: string
    /** Canvas dash pattern (e.g. `[3, 3]`) for the interior grid lines. Solid when omitted.
     *  The plot-edge baseline strokes stay solid either way — only the interior lines dash. */
    gridDash?: number[]
    /** Draw the solid plot-edge baseline strokes framing the grid (both value-axis edges).
     *  Defaults to true. Charts drawing their own axis lines pass false — the L-axis replaces the
     *  near baseline, and the far one would read as a stray border. */
    frame?: boolean
    orientation?: 'vertical' | 'horizontal'
    /** Cross-axis grid line positions (x-pixels in vertical mode, y-pixels in horizontal). */
    categoryTicks?: number[]
}

/** Draws the grid lines and the full plot-area frame.
 *
 * `orientation`:
 *  - `'vertical'` (default): horizontal grid lines at value-axis (y) tick positions, vertical baselines on both left and right.
 *  - `'horizontal'`: vertical grid lines at value-axis (x) tick positions, horizontal baselines on both top and bottom.
 *
 * In both modes, `yScale` maps a value to a pixel on the value axis — for vertical that's a y-pixel,
 * for horizontal that's an x-pixel. The function uses `dimensions` to size the perpendicular axis.
 */
export function drawGrid(drawCtx: DrawContext, options: DrawGridOptions = {}): void {
    const { ctx, yScale, dimensions } = drawCtx
    const gridColor = options.gridColor ?? 'rgba(0, 0, 0, 0.1)'
    const orientation = options.orientation ?? 'vertical'
    const tickAxisLength = orientation === 'horizontal' ? dimensions.plotWidth : dimensions.plotHeight
    const categoryTicks = options.categoryTicks ?? []

    const valueTicks = (yScale as ScaleLinear<number, number>).ticks?.(yTickCountForHeight(tickAxisLength)) ?? []
    const frame = options.frame ?? true

    ctx.strokeStyle = gridColor
    ctx.lineWidth = 1
    ctx.setLineDash(options.gridDash ?? [])

    // Skip the first category tick when it falls right next to the axis baseline
    // (left edge in vertical mode, top edge in horizontal) — otherwise it renders
    // as a faint second line hugging the axis.
    const AXIS_BASELINE_GAP = 4

    if (orientation === 'horizontal') {
        for (const tick of valueTicks) {
            const coord = yScale(tick)
            // In axis-line (frameless) mode, skip grid lines hugging the left edge — they'd double
            // up against the chart-drawn value-axis line. Framed grids keep their baseline gridline.
            if (!frame && coord - dimensions.plotLeft < AXIS_BASELINE_GAP) {
                continue
            }
            const x = snapToPixel(coord)
            ctx.beginPath()
            ctx.moveTo(x, dimensions.plotTop)
            ctx.lineTo(x, dimensions.plotTop + dimensions.plotHeight)
            ctx.stroke()
        }
        for (const coord of categoryTicks) {
            if (!isFinite(coord) || coord - dimensions.plotTop < AXIS_BASELINE_GAP) {
                continue
            }
            const y = snapToPixel(coord)
            ctx.beginPath()
            ctx.moveTo(dimensions.plotLeft, y)
            ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, y)
            ctx.stroke()
        }
        ctx.setLineDash([])
        if (frame) {
            const axisY = snapToPixel(dimensions.plotTop)
            ctx.beginPath()
            ctx.moveTo(dimensions.plotLeft, axisY)
            ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, axisY)
            ctx.stroke()
            // snapToPixel (Math.round + 0.5) matches the value-tick gridlines and drawAxes' baseline,
            // so a gridline or axis line at the plot bottom coincides exactly with this closing stroke
            // instead of landing 1px apart and doubling.
            const closingY = snapToPixel(dimensions.plotTop + dimensions.plotHeight)
            ctx.beginPath()
            ctx.moveTo(dimensions.plotLeft, closingY)
            ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, closingY)
            ctx.stroke()
        }
        return
    }

    for (const tick of valueTicks) {
        const coord = yScale(tick)
        // In axis-line (frameless) mode, skip grid lines hugging the bottom edge — they'd double
        // up against the chart-drawn x-axis line. Framed grids keep their baseline gridline.
        if (!frame && dimensions.plotTop + dimensions.plotHeight - coord < AXIS_BASELINE_GAP) {
            continue
        }
        const y = snapToPixel(coord)
        ctx.beginPath()
        ctx.moveTo(dimensions.plotLeft, y)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, y)
        ctx.stroke()
    }

    for (const coord of categoryTicks) {
        if (!isFinite(coord) || coord - dimensions.plotLeft < AXIS_BASELINE_GAP) {
            continue
        }
        const x = snapToPixel(coord)
        ctx.beginPath()
        ctx.moveTo(x, dimensions.plotTop)
        ctx.lineTo(x, dimensions.plotTop + dimensions.plotHeight)
        ctx.stroke()
    }

    ctx.setLineDash([])
    if (frame) {
        const axisX = snapToPixel(dimensions.plotLeft)
        ctx.beginPath()
        ctx.moveTo(axisX, dimensions.plotTop)
        ctx.lineTo(axisX, dimensions.plotTop + dimensions.plotHeight)
        ctx.stroke()

        // snapToPixel keeps this closing stroke on the same half-pixel grid as the value/category
        // gridlines and drawAxes' baseline (see the horizontal-mode block), so coincident strokes align.
        const closingX = snapToPixel(dimensions.plotLeft + dimensions.plotWidth)
        ctx.beginPath()
        ctx.moveTo(closingX, dimensions.plotTop)
        ctx.lineTo(closingX, dimensions.plotTop + dimensions.plotHeight)
        ctx.stroke()
    }
}

export function drawCrosshair(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    coord: number,
    color: string,
    orientation: 'vertical' | 'horizontal' = 'vertical',
    dash?: number[]
): void {
    // 0.5 offset keeps the 1px line crisp on integer pixel boundaries.
    const line = Math.round(coord) + 0.5
    ctx.strokeStyle = color
    ctx.lineWidth = 1
    ctx.setLineDash(dash ?? [])
    ctx.beginPath()
    if (orientation === 'vertical') {
        ctx.moveTo(line, dimensions.plotTop)
        ctx.lineTo(line, dimensions.plotTop + dimensions.plotHeight)
    } else {
        ctx.moveTo(dimensions.plotLeft, line)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, line)
    }
    ctx.stroke()
    ctx.setLineDash([])
}

export interface BarRoundedCorners {
    topLeft?: boolean
    topRight?: boolean
    bottomLeft?: boolean
    bottomRight?: boolean
}

/** Caller owns beginPath / fill / stroke; this only emits the path. */
export function traceRoundedBarPath(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number,
    corners: BarRoundedCorners
): void {
    const r = Math.max(0, Math.min(radius, Math.abs(width) / 2, Math.abs(height) / 2))
    const tl = corners.topLeft ? r : 0
    const tr = corners.topRight ? r : 0
    const br = corners.bottomRight ? r : 0
    const bl = corners.bottomLeft ? r : 0
    ctx.moveTo(x + tl, y)
    ctx.lineTo(x + width - tr, y)
    if (tr > 0) {
        ctx.quadraticCurveTo(x + width, y, x + width, y + tr)
    }
    ctx.lineTo(x + width, y + height - br)
    if (br > 0) {
        ctx.quadraticCurveTo(x + width, y + height, x + width - br, y + height)
    }
    ctx.lineTo(x + bl, y + height)
    if (bl > 0) {
        ctx.quadraticCurveTo(x, y + height, x, y + height - bl)
    }
    ctx.lineTo(x, y + tl)
    if (tl > 0) {
        ctx.quadraticCurveTo(x, y, x + tl, y)
    }
    ctx.closePath()
}

export interface BarRect {
    x: number
    y: number
    width: number
    height: number
    corners: BarRoundedCorners
    /** Index into the original `series.data` — partial-dash hatch ranges resolve against the
     *  source array, not against this bars[] which the caller may have pre-filtered. */
    dataIndex: number
}

export const DEFAULT_BAR_CORNER_RADIUS = 4

/** d3 `.darker()` factor for a bar's hover highlight — shared by BarChart and ComboChart so the
 *  hovered-bar shade stays consistent. */
export const BAR_HIGHLIGHT_DARKEN = 0.6

/** Run `draw` with the canvas clipped to the plot area vertically (full width, padded `pad` px top
 *  and bottom). Keeps out-of-domain values (e.g. a trendline below 0) out of the axis gutters while
 *  leaving the left/right edges unclipped so line caps and edge point markers render whole.
 *  `clipLeft` additionally trims at the plot's left edge — for charts drawing a y-axis line, so the
 *  first point's stroke ends at the axis instead of bulging past it into the gutter. Shared by
 *  LineChart and ComboChart. `restore` always runs, even if `draw` throws. */
export function withVerticalClip(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    draw: () => void,
    pad = 8,
    clipLeft = false
): void {
    // Matches drawAxes' snapping: the axis line's 1px column starts at round(plotLeft), so trimming
    // there leaves the stroke flush against the axis line.
    const left = clipLeft ? Math.round(dimensions.plotLeft) : 0
    ctx.save()
    ctx.beginPath()
    ctx.rect(left, dimensions.plotTop - pad, dimensions.width - left, dimensions.plotHeight + pad * 2)
    ctx.clip()
    try {
        draw()
    } finally {
        ctx.restore()
    }
}

export interface LineSeriesLayerOptions {
    ctx: CanvasRenderingContext2D
    dimensions: ChartDimensions
    labels: string[]
    /** Series to draw, in paint order. Excluded series are skipped. */
    series: readonly ResolvedSeries[]
    xScale: (label: string) => number | undefined
    resolveYScale: (s: ResolvedSeries) => ScaleLinear<number, number> | ScaleLogarithmic<number, number>
    /** y-values to plot for a series (e.g. stacked tops). Defaults to `series.data`. */
    yValuesFor?: (s: ResolvedSeries) => number[] | undefined
    /** Bottom edge for the area fill (stacked bottom or `fill.lowerData`). */
    bottomFor?: (s: ResolvedSeries) => number[] | undefined
    /** Whether to fill the area under a series. Defaults to `!!s.fill`. */
    shouldFill?: (s: ResolvedSeries) => boolean
    /** `per-series`: area then line+points per series (LineChart). `areas-first`: every area, then
     *  every line+points (ComboChart) so a later area can't paint over an earlier line. */
    zOrder?: 'per-series' | 'areas-first'
    /** Smooth lines/areas with monotone-cubic interpolation instead of straight segments. */
    smooth?: boolean
    /** See {@link DrawContext.yFloor} — rest baseline-hugging strokes on the axis line. */
    yFloor?: number
    /** Trim strokes at the plot's left edge so they end at a drawn y-axis line instead of bulging
     *  past it. Pass the chart's `showAxisLines` — without an axis line the overhang is invisible
     *  and edge line caps are left whole. */
    clipLeftEdge?: boolean
}

/** Draw a line/area layer (clipped vertically) — the per-series area/line/points orchestration shared
 *  by LineChart and ComboChart. Callers supply the y-value source (raw vs stacked tops), the fill
 *  predicate, and the z-order; the loop, clip, and primitive calls live here. */
export function drawLineSeriesLayer(options: LineSeriesLayerOptions): void {
    const { ctx, dimensions, labels, series, xScale, resolveYScale, smooth, yFloor, clipLeftEdge } = options
    const yValuesFor = options.yValuesFor ?? (() => undefined)
    const bottomFor = options.bottomFor ?? ((s: ResolvedSeries) => s.fill?.lowerData)
    const shouldFill = options.shouldFill ?? ((s: ResolvedSeries) => !!s.fill)
    const zOrder = options.zOrder ?? 'per-series'
    const visible = series.filter((s) => !s.visibility?.excluded)

    const paintArea = (s: ResolvedSeries): void => {
        if (!shouldFill(s)) {
            return
        }
        drawArea(
            { ctx, dimensions, labels, xScale, yScale: resolveYScale(s), smooth, yFloor },
            s,
            yValuesFor(s),
            bottomFor(s)
        )
    }
    const paintLine = (s: ResolvedSeries): void => {
        if (s.fill?.lowerData) {
            return
        }
        const drawCtx: DrawContext = { ctx, dimensions, labels, xScale, yScale: resolveYScale(s), smooth, yFloor }
        drawLine(drawCtx, s, yValuesFor(s))
        drawPoints(drawCtx, s, yValuesFor(s))
    }

    withVerticalClip(
        ctx,
        dimensions,
        () => {
            if (zOrder === 'areas-first') {
                for (const s of visible) {
                    paintArea(s)
                }
                for (const s of visible) {
                    paintLine(s)
                }
                return
            }
            for (const s of visible) {
                paintArea(s)
                paintLine(s)
            }
        },
        undefined,
        clipLeftEdge
    )
}

/** Draw hover highlight rings for line/area series at the hovered index. Skips excluded,
 *  fill-between (`fill.lowerData`), and overlay series (trendlines/moving averages opt out of hover
 *  points). `pointFor` lets each chart supply its own anchor — LineChart resolves the point x and
 *  stacked-top y per series; ComboChart anchors at the band center with raw values. Returns whether
 *  any point was drawn. Shared by LineChart and ComboChart. */
export function drawLineHoverPoints(
    ctx: CanvasRenderingContext2D,
    series: readonly ResolvedSeries[],
    backgroundColor: string,
    pointFor: (s: ResolvedSeries) => { x: number; y: number } | null
): boolean {
    let drew = false
    for (const s of series) {
        if (s.visibility?.excluded || s.fill?.lowerData || s.overlay) {
            continue
        }
        const point = pointFor(s)
        if (point && isFinite(point.x) && isFinite(point.y)) {
            drawHighlightPoint(ctx, point.x, point.y, s.color, backgroundColor)
            drew = true
        }
    }
    return drew
}

export interface BarShadow {
    color: string
    blur: number
    offsetX?: number
    offsetY?: number
}

const BAR_FILL_LIGHTEN = 0.22
const BAR_FILL_DARKEN = 0.16

/** Bar fill for a given style. `gradient` is a diagonal (top-left → bottom-right) light→dark sheen
 *  matching the PostHog logo's light direction; `gloss` is a curved radial highlight. */
function makeBarFill(
    ctx: CanvasRenderingContext2D,
    color: string,
    bar: BarRect,
    style: BarFillStyle
): string | CanvasGradient {
    if (style === 'flat') {
        return color
    }
    const light = mixColors(color, '#ffffff', BAR_FILL_LIGHTEN)
    const dark = mixColors(color, '#000000', BAR_FILL_DARKEN)
    if (style === 'gloss') {
        // Curved highlight: a radial sheen rising from a focus near the top, so the light falls off
        // in arcs for a glassy, rounded look rather than a flat linear band.
        const cx = bar.x + bar.width * 0.5
        const cy = bar.y + bar.height * 0.12
        const radius = Math.max(bar.width, bar.height) * 0.95
        const radial = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
        radial.addColorStop(0, light)
        radial.addColorStop(0.45, color)
        radial.addColorStop(1, dark)
        return radial
    }
    // gradient — smooth diagonal light → dark
    const gradient = ctx.createLinearGradient(bar.x, bar.y, bar.x + bar.width, bar.y + bar.height)
    gradient.addColorStop(0, light)
    gradient.addColorStop(1, dark)
    return gradient
}

/** Hatch ranges (`series.stroke?.partial`) clamp against `series.data.length`. Any ctx
 *  state (shadow / clip / globalAlpha) is the caller's responsibility. */
export function drawBars(
    drawCtx: DrawContext,
    series: ResolvedSeries,
    bars: BarRect[],
    cornerRadius: number = DEFAULT_BAR_CORNER_RADIUS,
    fillStyle: BarFillStyle = 'flat'
): void {
    const { ctx } = drawCtx
    if (bars.length === 0) {
        return
    }

    const dataLength = series.data.length
    const dashedFrom = resolvePartialIndex(series.stroke?.partial?.fromIndex, dataLength)
    const dashedTo = resolvePartialIndex(series.stroke?.partial?.toIndex, dataLength)
    const hatch = dashedFrom !== null || dashedTo !== null ? getHatchPattern(ctx, series.color) : null

    for (const bar of bars) {
        if (bar.width <= 0 || bar.height <= 0) {
            continue
        }
        const useHatch =
            hatch !== null &&
            ((dashedFrom !== null && bar.dataIndex >= dashedFrom) || (dashedTo !== null && bar.dataIndex <= dashedTo))
        ctx.fillStyle = useHatch ? hatch : makeBarFill(ctx, barColorAt(series, bar.dataIndex), bar, fillStyle)
        ctx.beginPath()
        traceRoundedBarPath(ctx, bar.x, bar.y, bar.width, bar.height, cornerRadius, bar.corners)
        ctx.fill()
    }
}

// Tracks render as a tinted base under hatched stripes — same construction as the legacy
// funnel backdrop (`var(--series-color)` behind `repeating-linear-gradient` stripes), so the
// whole region reads as continuously filled rather than as bare stripes on the background.
const BAR_TRACK_BASE_ALPHA = 0.14
const BAR_TRACK_HATCH_ALPHA = 0.18
/** Translucent overlay drawn over the track on hover. Exported so the chart-type's
 *  hover callback can match the resting track's tuning. */
export const BAR_TRACK_HOVER_ALPHA = 0.2

function fillTrackRects(ctx: CanvasRenderingContext2D, tracks: BarRect[], cornerRadius: number): void {
    for (const track of tracks) {
        ctx.beginPath()
        traceRoundedBarPath(ctx, track.x, track.y, track.width, track.height, cornerRadius, track.corners)
        ctx.fill()
    }
}

/** Clips subsequent drawing to the union of the given rounded rects — used to mask the bar
 *  layer to the funnel pill so a stack's outer corners round even when the edge segment is too
 *  thin to round on its own. Caller owns save/restore. */
export function clipToRoundedRects(ctx: CanvasRenderingContext2D, rects: BarRect[], cornerRadius: number): void {
    const renderableRects = rects.filter((r) => r.width > 0 && r.height > 0)
    if (renderableRects.length === 0) {
        return
    }
    ctx.beginPath()
    for (const r of renderableRects) {
        traceRoundedBarPath(ctx, r.x, r.y, r.width, r.height, cornerRadius, r.corners)
    }
    ctx.clip()
}

/** Paints each track rect as a single solid colour — the neutral "remainder of the whole"
 *  backdrop for funnel-style stacked bars (one track per band behind the stack), as opposed
 *  to {@link drawBarTracks}'s per-series tinted+hatched treatment for grouped layouts. */
export function drawSolidBarTracks(
    ctx: CanvasRenderingContext2D,
    tracks: BarRect[],
    color: string,
    cornerRadius: number
): void {
    const renderableTracks = tracks.filter((t) => t.width > 0 && t.height > 0)
    if (renderableTracks.length === 0) {
        return
    }
    ctx.save()
    ctx.fillStyle = color
    fillTrackRects(ctx, renderableTracks, cornerRadius)
    ctx.restore()
}

/** Paints each track rect as a tinted base under hatched stripes. Takes laid-out rects
 *  from `computeBarTrackRect`, mirroring `drawBars`. */
export function drawBarTracks(
    drawCtx: DrawContext,
    series: ResolvedSeries,
    tracks: BarRect[],
    cornerRadius: number
): void {
    const renderableTracks = tracks.filter((t) => t.width > 0 && t.height > 0)
    if (renderableTracks.length === 0) {
        return
    }
    const { ctx } = drawCtx
    ctx.save()
    // Solid base fill — what makes the region differ from the background, even between stripes.
    ctx.globalAlpha = BAR_TRACK_BASE_ALPHA
    ctx.fillStyle = series.color
    fillTrackRects(ctx, renderableTracks, cornerRadius)
    // Hatched stripes on top.
    ctx.globalAlpha = BAR_TRACK_HATCH_ALPHA
    ctx.fillStyle = getHatchPattern(ctx, series.color)
    fillTrackRects(ctx, renderableTracks, cornerRadius)
    ctx.restore()
}

/** Translucent fill on the overlay canvas, alpha-composited over the static bar. */
export function drawBarHighlight(
    ctx: CanvasRenderingContext2D,
    bar: BarRect,
    overlayColor: string,
    cornerRadius: number = DEFAULT_BAR_CORNER_RADIUS
): void {
    if (bar.width <= 0 || bar.height <= 0) {
        return
    }
    ctx.fillStyle = overlayColor
    ctx.beginPath()
    traceRoundedBarPath(ctx, bar.x, bar.y, bar.width, bar.height, cornerRadius, bar.corners)
    ctx.fill()
}

export function drawHighlightPoint(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    color: string,
    backgroundColor: string,
    radius: number = 4
): void {
    ctx.fillStyle = backgroundColor
    ctx.beginPath()
    ctx.arc(x, y, radius + 2, 0, Math.PI * 2)
    ctx.fill()

    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    ctx.fill()
}

export interface DrawBoxOptions {
    /** Series base color — used for the box outline, whisker, median, and mean stroke. */
    color: string
    /** Box fill — typically the series color at reduced alpha. */
    fillColor: string
    /** Optional explicit median stroke color. Defaults to `color`. */
    medianColor?: string
    /** Optional mean marker fill. Defaults to `fillColor`. */
    meanFillColor?: string
    /** Mean marker radius in CSS pixels. Defaults to 3. */
    meanRadius?: number
    /** Line width for the box outline, whiskers, and median. Defaults to 1.5. */
    lineWidth?: number
    /** Width of the whisker caps (as a fraction of the box width). Defaults to 0.6. */
    whiskerCapRatio?: number
}

/** Paint a whole series of box-and-whiskers, batching path operations so the number of
 *  `beginPath`/`stroke` pairs is `4 + N` instead of `5N` (whisker stems, caps, box outlines,
 *  and medians are each one shared path; mean markers stay per-box since each needs both
 *  fill and stroke). Pure: takes pre-laid-out {@link BoxRect}s; no scale access. */
export function drawBoxes(ctx: CanvasRenderingContext2D, boxes: BoxRect[], options: DrawBoxOptions): void {
    if (boxes.length === 0) {
        return
    }
    const {
        color,
        fillColor,
        medianColor = color,
        meanFillColor = fillColor,
        meanRadius = 3,
        lineWidth = 1.5,
        whiskerCapRatio = 0.6,
    } = options

    ctx.lineWidth = lineWidth
    ctx.strokeStyle = color
    ctx.setLineDash([])

    // 1. Whisker stems — only emit a stem when the whisker extends past the box edge.
    ctx.beginPath()
    for (const box of boxes) {
        const centerX = box.x + box.width / 2
        if (box.whiskerTop < box.top) {
            ctx.moveTo(centerX, box.whiskerTop)
            ctx.lineTo(centerX, box.top)
        }
        if (box.whiskerBottom > box.bottom) {
            ctx.moveTo(centerX, box.bottom)
            ctx.lineTo(centerX, box.whiskerBottom)
        }
    }
    ctx.stroke()

    // 2. Whisker caps — skip the cap whenever the corresponding stem was skipped, otherwise
    //    a cross-bar would paint on top of the box outline for collapsed distributions
    //    (`min == p25` / `max == p75`).
    ctx.beginPath()
    for (const box of boxes) {
        const centerX = box.x + box.width / 2
        const capHalfWidth = (box.width * whiskerCapRatio) / 2
        if (box.whiskerTop < box.top) {
            ctx.moveTo(centerX - capHalfWidth, box.whiskerTop)
            ctx.lineTo(centerX + capHalfWidth, box.whiskerTop)
        }
        if (box.whiskerBottom > box.bottom) {
            ctx.moveTo(centerX - capHalfWidth, box.whiskerBottom)
            ctx.lineTo(centerX + capHalfWidth, box.whiskerBottom)
        }
    }
    ctx.stroke()

    // 3. Box rectangles (p25 → p75) — fill then outline. `fillRect` / `strokeRect` are
    //    already optimal — no `beginPath` accumulation needed.
    ctx.fillStyle = fillColor
    for (const box of boxes) {
        const boxHeight = Math.max(0, box.bottom - box.top)
        if (boxHeight > 0 && box.width > 0) {
            ctx.fillRect(box.x, box.top, box.width, boxHeight)
            ctx.strokeRect(box.x, box.top, box.width, boxHeight)
        }
    }

    // 4. Median lines.
    ctx.strokeStyle = medianColor
    ctx.beginPath()
    for (const box of boxes) {
        const medianClamped = Math.max(box.top, Math.min(box.bottom, box.medianY))
        ctx.moveTo(box.x, medianClamped)
        ctx.lineTo(box.x + box.width, medianClamped)
    }
    ctx.stroke()

    // 5. Mean markers — filled circle outlined in the series color. Stays per-box because
    //    each marker requires both a fill and a stroke pass.
    ctx.fillStyle = meanFillColor
    ctx.strokeStyle = color
    for (const box of boxes) {
        ctx.beginPath()
        ctx.arc(box.mean.x, box.mean.y, meanRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
    }
}

/** Translucent highlight overlay for a hovered box. Drawn on the overlay canvas so it
 *  composites over the static box without disturbing it — mirrors {@link drawBarHighlight}. */
export function drawBoxHighlight(ctx: CanvasRenderingContext2D, box: BoxRect, overlayColor: string): void {
    const boxHeight = Math.max(0, box.bottom - box.top)
    if (box.width <= 0 || boxHeight <= 0) {
        return
    }
    ctx.fillStyle = overlayColor
    ctx.fillRect(box.x, box.top, box.width, boxHeight)
}

type DrawHoverFn = (args: ChartDrawArgs) => DrawHoverResult

interface ComposeDrawHoverOptions {
    crosshairColor: string | undefined
    crosshairDash?: number[]
    showCrosshair: boolean
    axisOrientation?: 'vertical' | 'horizontal'
    labelToCoord?: (label: string) => number | undefined
}

// Crosshair drawn first so the chart-type's highlight rings render on top.
export function composeDrawHoverWithCrosshair(
    getDrawHover: () => DrawHoverFn,
    options: ComposeDrawHoverOptions
): DrawHoverFn {
    const { crosshairColor, crosshairDash, showCrosshair, axisOrientation = 'vertical', labelToCoord } = options
    return (args) => {
        if (showCrosshair && crosshairColor && args.hoverIndex >= 0) {
            const label = args.labels[args.hoverIndex]
            const coord = labelToCoord ? labelToCoord(label) : args.scales.x(label)
            if (coord != null && isFinite(coord)) {
                drawCrosshair(args.ctx, args.dimensions, coord, crosshairColor, axisOrientation, crosshairDash)
            }
        }
        return getDrawHover()(args)
    }
}

// Drag-selection band styling. Intentionally a fixed accent rather than a theme token: there's no
// selection color in the design tokens yet, and the band is a transient interaction affordance, not
// chart data. Add a `--color-graph-selection-*` token and thread it through here if it needs theming.
const SELECTION_FILL = 'rgba(59, 130, 246, 0.15)'
const SELECTION_STROKE = 'rgba(59, 130, 246, 0.5)'
const SELECTION_LINE_WIDTH = 1

export function drawSelectionRect(
    ctx: CanvasRenderingContext2D,
    rect: { x: number; y: number; width: number; height: number }
): void {
    if (rect.width <= 0 || rect.height <= 0) {
        return
    }
    ctx.fillStyle = SELECTION_FILL
    ctx.fillRect(rect.x, rect.y, rect.width, rect.height)
    ctx.strokeStyle = SELECTION_STROKE
    ctx.lineWidth = SELECTION_LINE_WIDTH
    ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.width - 1, rect.height - 1)
}

// The selection always spans the full plot height — this is x-axis range selection only.
export function composeDrawHoverWithSelection(baseDrawHover: DrawHoverFn): DrawHoverFn {
    return (args) => {
        const result = baseDrawHover(args)
        const dragRect = args.dragRect
        if (!dragRect) {
            return result
        }
        const x0 = Math.max(args.dimensions.plotLeft, Math.min(dragRect.x0, dragRect.x1))
        const x1 = Math.min(args.dimensions.plotLeft + args.dimensions.plotWidth, Math.max(dragRect.x0, dragRect.x1))
        if (x1 <= x0) {
            return result
        }
        drawSelectionRect(args.ctx, {
            x: x0,
            y: args.dimensions.plotTop,
            width: x1 - x0,
            height: args.dimensions.plotHeight,
        })
        return result
    }
}
