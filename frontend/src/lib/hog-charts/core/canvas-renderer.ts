import * as d3 from 'd3'

import type { ChartDimensions, Series } from './types'

export interface DrawContext {
    ctx: CanvasRenderingContext2D
    dimensions: ChartDimensions
    xScale: d3.ScalePoint<string>
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    labels: string[]
}

export function drawLine(drawCtx: DrawContext, series: Series, yValues?: number[]): void {
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
 * Splits the line into strokes based on `dashedFromIndex`/`dashedToIndex`. Each entry is a
 * contiguous index range drawn with a single dash pattern; adjacent strokes share their
 * boundary index so the visual seam between them is invisible.
 */
function planLineStrokes(series: Series, length: number): Stroke[] {
    const basePattern = series.dashPattern ?? []
    const partialPattern = series.dashedPattern ?? [10, 10]
    const from = resolveDashedFromIndex(series.dashedFromIndex, length)
    const to = resolveDashedToIndex(series.dashedToIndex, length)

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

/** Returns null when unset or past the end; otherwise rounds and clamps into [0, length-1]. */
function resolveDashedFromIndex(idx: number | undefined, length: number): number | null {
    if (idx == null) {
        return null
    }
    const rounded = Math.round(idx)
    if (rounded >= length) {
        return null
    }
    return Math.max(0, rounded)
}

/** Returns null when unset or before the start; otherwise rounds and clamps into [0, length-1]. */
function resolveDashedToIndex(idx: number | undefined, length: number): number | null {
    if (idx == null) {
        return null
    }
    const rounded = Math.round(idx)
    if (rounded < 0) {
        return null
    }
    return Math.min(length - 1, rounded)
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

export function drawArea(drawCtx: DrawContext, series: Series, yValues?: number[], bottomValues?: number[]): void {
    const { ctx, xScale, yScale, labels, dimensions } = drawCtx
    const data = yValues ?? series.data
    const opacity = series.fillOpacity ?? 0.5
    const baseline = dimensions.plotTop + dimensions.plotHeight
    const dashedFrom = resolveDashedFromIndex(series.dashedFromIndex, data.length)

    const segments: { top: AreaPoint[]; bottom: AreaPoint[] }[] = []
    let currentTop: AreaPoint[] = []
    let currentBottom: AreaPoint[] = []
    for (let i = 0; i < data.length; i++) {
        const x = xScale(labels[i])
        const yTop = yScale(data[i])
        if (x != null && isFinite(yTop)) {
            currentTop.push({ x, y: yTop, dataIndex: i })
            const yBot = bottomValues ? yScale(bottomValues[i]) : baseline
            currentBottom.push({ x, y: isFinite(yBot) ? yBot : baseline, dataIndex: i })
        } else if (currentTop.length > 0) {
            segments.push({ top: currentTop, bottom: currentBottom })
            currentTop = []
            currentBottom = []
        }
    }
    if (currentTop.length > 0) {
        segments.push({ top: currentTop, bottom: currentBottom })
    }

    ctx.globalAlpha = opacity

    for (const { top, bottom } of segments) {
        if (top.length < 2) {
            continue
        }

        if (dashedFrom === null) {
            ctx.fillStyle = series.color
            fillAreaPath(ctx, top, bottom)
        } else {
            const splitIdx = top.findIndex((p) => p.dataIndex >= dashedFrom)

            if (splitIdx === -1) {
                ctx.fillStyle = series.color
                fillAreaPath(ctx, top, bottom)
            } else if (splitIdx > 0) {
                ctx.fillStyle = series.color
                fillAreaPath(ctx, top.slice(0, splitIdx + 1), bottom.slice(0, splitIdx + 1))
            }

            if (splitIdx >= 0 && splitIdx < top.length) {
                const hatchStart = Math.max(0, splitIdx - 1)
                ctx.fillStyle = getHatchPattern(ctx, series.color)
                fillAreaPath(ctx, top.slice(hatchStart), bottom.slice(hatchStart))
            }
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

export function drawPoints(drawCtx: DrawContext, series: Series, yValues?: number[]): void {
    const { ctx, xScale, yScale, labels } = drawCtx
    const data = yValues ?? series.data
    const radius = series.pointRadius ?? 0

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

export function drawGrid(drawCtx: DrawContext, options: { gridColor?: string } = {}): void {
    const { ctx, yScale, dimensions } = drawCtx
    const gridColor = options.gridColor ?? 'rgba(0, 0, 0, 0.1)'

    const yTicks = (yScale as d3.ScaleLinear<number, number>).ticks?.() ?? []

    ctx.strokeStyle = gridColor
    ctx.lineWidth = 1
    ctx.setLineDash([])

    for (const tick of yTicks) {
        const y = Math.round(yScale(tick)) + 0.5
        ctx.beginPath()
        ctx.moveTo(dimensions.plotLeft, y)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, y)
        ctx.stroke()
    }
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
