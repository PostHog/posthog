import * as d3 from 'd3'

import { yTickCountForHeight } from './scales'
import type { ChartDimensions, ChartDrawArgs, DrawHoverResult, ResolvedSeries } from './types'

export interface DrawContext {
    ctx: CanvasRenderingContext2D
    dimensions: ChartDimensions
    xScale: (label: string) => number | undefined
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    labels: string[]
}

export function drawLine(drawCtx: DrawContext, series: ResolvedSeries, yValues?: number[]): void {
    const data = yValues ?? series.data
    if (data.length === 0) {
        return
    }

    const { ctx } = drawCtx
    ctx.strokeStyle = series.color
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    for (const { start, end, pattern } of planLineStrokes(series, data.length)) {
        ctx.beginPath()
        ctx.setLineDash(pattern)
        tracePath(drawCtx, data, start, end)
        ctx.stroke()
    }
    ctx.setLineDash([])
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

/** Walks data from [start, end] inclusive, emitting moveTo/lineTo. Caller owns beginPath/stroke. */
function tracePath(drawCtx: DrawContext, data: number[], start: number, end: number): void {
    const { ctx, xScale, yScale, labels } = drawCtx
    let started = false
    for (let i = start; i <= end; i++) {
        const x = xScale(labels[i])
        const y = yScale(data[i])
        if (x == null || !isFinite(y)) {
            // Reset so the next valid point starts a fresh subpath rather than
            // connecting straight across the NaN gap.
            started = false
            continue
        }
        if (!started) {
            ctx.moveTo(x, y)
            started = true
        } else {
            ctx.lineTo(x, y)
        }
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
    const { ctx, xScale, yScale, labels, dimensions } = drawCtx
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
        const yTop = yScale(data[i])
        if (x == null || !isFinite(yTop)) {
            breakSegment()
            continue
        }
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

    // Gradient applies only to the un-stacked baseline fill; dashed-partial segments
    // stay on a solid fill via the branch below.
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

        if (dashedFrom === null && dashedTo === null) {
            ctx.fillStyle = gradient ?? series.color
            fillAreaPath(ctx, top, bottom)
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
            fillAreaPath(ctx, top, bottom)
            continue
        }

        if (dashedTo !== null && toSplit > 0) {
            const leadingEnd = Math.min(top.length, toSplit + 1)
            ctx.fillStyle = hatch
            fillAreaPath(ctx, top.slice(0, leadingEnd), bottom.slice(0, leadingEnd))
        }

        const solidStart = toSplit === -1 ? 0 : toSplit
        const solidEnd = fromSplit === -1 ? top.length : fromSplit

        if (solidEnd - solidStart >= 2) {
            const trailingHatchPresent = dashedFrom !== null && fromSplit !== -1
            const slicedEnd = trailingHatchPresent ? Math.min(top.length, solidEnd + 1) : solidEnd
            ctx.fillStyle = series.color
            fillAreaPath(ctx, top.slice(solidStart, slicedEnd), bottom.slice(solidStart, slicedEnd))
        }

        if (dashedFrom !== null && fromSplit > 0) {
            const hatchStart = Math.max(0, fromSplit - 1)
            ctx.fillStyle = hatch
            fillAreaPath(ctx, top.slice(hatchStart), bottom.slice(hatchStart))
        }
    }

    ctx.globalAlpha = 1
}

function fillAreaPath(
    ctx: CanvasRenderingContext2D,
    top: { x: number; y: number }[],
    bottom: { x: number; y: number }[]
): void {
    ctx.beginPath()
    ctx.moveTo(top[0].x, top[0].y)
    for (let i = 1; i < top.length; i++) {
        ctx.lineTo(top[i].x, top[i].y)
    }
    for (let i = bottom.length - 1; i >= 0; i--) {
        ctx.lineTo(bottom[i].x, bottom[i].y)
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

export interface DrawGridOptions {
    gridColor?: string
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

    const valueTicks = (yScale as d3.ScaleLinear<number, number>).ticks?.(yTickCountForHeight(tickAxisLength)) ?? []

    ctx.strokeStyle = gridColor
    ctx.lineWidth = 1
    ctx.setLineDash([])

    // Skip the first category tick when it falls right next to the axis baseline
    // (left edge in vertical mode, top edge in horizontal) — otherwise it renders
    // as a faint second line hugging the axis.
    const AXIS_BASELINE_GAP = 4

    if (orientation === 'horizontal') {
        for (const tick of valueTicks) {
            const x = Math.round(yScale(tick)) + 0.5
            ctx.beginPath()
            ctx.moveTo(x, dimensions.plotTop)
            ctx.lineTo(x, dimensions.plotTop + dimensions.plotHeight)
            ctx.stroke()
        }
        for (const coord of categoryTicks) {
            if (!isFinite(coord) || coord - dimensions.plotTop < AXIS_BASELINE_GAP) {
                continue
            }
            const y = Math.round(coord) + 0.5
            ctx.beginPath()
            ctx.moveTo(dimensions.plotLeft, y)
            ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, y)
            ctx.stroke()
        }
        const axisY = Math.round(dimensions.plotTop) + 0.5
        ctx.beginPath()
        ctx.moveTo(dimensions.plotLeft, axisY)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, axisY)
        ctx.stroke()
        // Far-edge snap uses `- 0.5` (mirror of the `+ 0.5` near edge above) so the
        // closing stroke lands just inside `plotTop + plotHeight` and stays within the plot rect.
        const closingY = Math.round(dimensions.plotTop + dimensions.plotHeight) - 0.5
        ctx.beginPath()
        ctx.moveTo(dimensions.plotLeft, closingY)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, closingY)
        ctx.stroke()
        return
    }

    for (const tick of valueTicks) {
        const y = Math.round(yScale(tick)) + 0.5
        ctx.beginPath()
        ctx.moveTo(dimensions.plotLeft, y)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, y)
        ctx.stroke()
    }

    for (const coord of categoryTicks) {
        if (!isFinite(coord) || coord - dimensions.plotLeft < AXIS_BASELINE_GAP) {
            continue
        }
        const x = Math.round(coord) + 0.5
        ctx.beginPath()
        ctx.moveTo(x, dimensions.plotTop)
        ctx.lineTo(x, dimensions.plotTop + dimensions.plotHeight)
        ctx.stroke()
    }

    const axisX = Math.round(dimensions.plotLeft) + 0.5
    ctx.beginPath()
    ctx.moveTo(axisX, dimensions.plotTop)
    ctx.lineTo(axisX, dimensions.plotTop + dimensions.plotHeight)
    ctx.stroke()

    // See the horizontal-mode block for the `- 0.5` snap rationale (mirror of the near-edge `+ 0.5`).
    const closingX = Math.round(dimensions.plotLeft + dimensions.plotWidth) - 0.5
    ctx.beginPath()
    ctx.moveTo(closingX, dimensions.plotTop)
    ctx.lineTo(closingX, dimensions.plotTop + dimensions.plotHeight)
    ctx.stroke()
}

export function drawCrosshair(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    coord: number,
    color: string,
    orientation: 'vertical' | 'horizontal' = 'vertical'
): void {
    // 0.5 offset keeps the 1px line crisp on integer pixel boundaries.
    const line = Math.round(coord) + 0.5
    ctx.strokeStyle = color
    ctx.lineWidth = 1
    ctx.setLineDash([])
    ctx.beginPath()
    if (orientation === 'vertical') {
        ctx.moveTo(line, dimensions.plotTop)
        ctx.lineTo(line, dimensions.plotTop + dimensions.plotHeight)
    } else {
        ctx.moveTo(dimensions.plotLeft, line)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, line)
    }
    ctx.stroke()
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

export interface BarShadow {
    color: string
    blur: number
    offsetX?: number
    offsetY?: number
}

/** Hatch ranges (`series.stroke?.partial`) clamp against `series.data.length`. Any ctx
 *  state (shadow / clip / globalAlpha) is the caller's responsibility. */
export function drawBars(
    drawCtx: DrawContext,
    series: ResolvedSeries,
    bars: BarRect[],
    cornerRadius: number = DEFAULT_BAR_CORNER_RADIUS
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
        ctx.fillStyle = useHatch ? hatch : series.color
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

/** A laid-out box-and-whisker for a single (series, x) slot. Same shape contract as
 *  {@link BarRect} — pre-computed pixel coordinates so the draw primitives don't touch scales. */
export interface BoxRect {
    x: number
    width: number
    top: number
    bottom: number
    medianY: number
    mean: { x: number; y: number }
    whiskerTop: number
    whiskerBottom: number
    dataIndex: number
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
    showCrosshair: boolean
    axisOrientation?: 'vertical' | 'horizontal'
    labelToCoord?: (label: string) => number | undefined
}

// Crosshair drawn first so the chart-type's highlight rings render on top.
export function composeDrawHoverWithCrosshair(
    getDrawHover: () => DrawHoverFn,
    options: ComposeDrawHoverOptions
): DrawHoverFn {
    const { crosshairColor, showCrosshair, axisOrientation = 'vertical', labelToCoord } = options
    return (args) => {
        if (showCrosshair && crosshairColor && args.hoverIndex >= 0) {
            const label = args.labels[args.hoverIndex]
            const coord = labelToCoord ? labelToCoord(label) : args.scales.x(label)
            if (coord != null && isFinite(coord)) {
                drawCrosshair(args.ctx, args.dimensions, coord, crosshairColor, axisOrientation)
            }
        }
        return getDrawHover()(args)
    }
}
