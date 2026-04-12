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
    const { ctx } = drawCtx
    const data = yValues ?? series.data
    const length = data.length

    if (length === 0) {
        return
    }

    ctx.strokeStyle = series.color
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    const defaultDash = series.dashPattern ?? []
    const dashedDash = series.dashedPattern ?? [10, 10]
    const from = normalizeDashedFrom(series.dashedFromIndex, length)
    const to = normalizeDashedTo(series.dashedToIndex, length)

    // Fast path: no partial dashing.
    if (from < 0 && to < 0) {
        strokeRange(drawCtx, data, 0, length - 1, defaultDash)
        ctx.setLineDash([])
        return
    }

    // Whole line dashed: dashed regions from either end meet or overlap.
    // - from === 0 → dashed from the very start
    // - to === length - 1 → dashed through the very end
    // - both set and dashed ranges meet (to >= from - 1) → no solid middle
    const wholeDashed = from === 0 || to === length - 1 || (from >= 0 && to >= 0 && to >= from - 1)
    if (wholeDashed) {
        strokeRange(drawCtx, data, 0, length - 1, dashedDash)
        ctx.setLineDash([])
        return
    }

    // Up to three subpaths. Adjacent subpaths share their boundary point so strokes stay seamless.
    if (to >= 0) {
        strokeRange(drawCtx, data, 0, to, dashedDash)
    }
    const solidStart = to >= 0 ? to : 0
    const solidEnd = from >= 0 ? from - 1 : length - 1
    // Skip a zero-length solid middle so the two dashed subpaths can sit directly adjacent.
    if (solidStart < solidEnd) {
        strokeRange(drawCtx, data, solidStart, solidEnd, defaultDash)
    }
    if (from >= 0) {
        strokeRange(drawCtx, data, from - 1, length - 1, dashedDash)
    }
    ctx.setLineDash([])
}

function strokeRange(drawCtx: DrawContext, data: number[], start: number, end: number, dashPattern: number[]): void {
    const { ctx, xScale, yScale, labels } = drawCtx
    ctx.beginPath()
    ctx.setLineDash(dashPattern)
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
    ctx.stroke()
}

/** -1 means "no dashed-from portion" (unset or out of range past the end). Otherwise clamped to [0, length-1]. */
function normalizeDashedFrom(idx: number | undefined, length: number): number {
    if (idx == null) {
        return -1
    }
    const rounded = Math.round(idx)
    if (rounded >= length) {
        return -1
    }
    return Math.max(0, rounded)
}

/** -1 means "no dashed-to portion" (unset or out of range before the start). Otherwise clamped to [0, length-1]. */
function normalizeDashedTo(idx: number | undefined, length: number): number {
    if (idx == null) {
        return -1
    }
    const rounded = Math.round(idx)
    if (rounded < 0) {
        return -1
    }
    return Math.min(length - 1, rounded)
}

export function drawArea(drawCtx: DrawContext, series: Series, yValues?: number[], bottomValues?: number[]): void {
    const { ctx, xScale, yScale, labels, dimensions } = drawCtx
    const data = yValues ?? series.data
    const opacity = series.fillOpacity ?? 0.5
    const baseline = dimensions.plotTop + dimensions.plotHeight

    // Split into contiguous segments to handle data gaps consistently with drawLine
    const segments: { top: { x: number; y: number }[]; bottom: { x: number; y: number }[] }[] = []
    let currentTop: { x: number; y: number }[] = []
    let currentBottom: { x: number; y: number }[] = []
    for (let i = 0; i < data.length; i++) {
        const x = xScale(labels[i])
        const yTop = yScale(data[i])
        if (x != null && isFinite(yTop)) {
            currentTop.push({ x, y: yTop })
            const yBot = bottomValues ? yScale(bottomValues[i]) : baseline
            currentBottom.push({ x, y: isFinite(yBot) ? yBot : baseline })
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
    ctx.fillStyle = series.color

    for (const { top, bottom } of segments) {
        if (top.length < 2) {
            continue
        }
        ctx.beginPath()
        ctx.moveTo(top[0].x, top[0].y)
        for (let i = 1; i < top.length; i++) {
            ctx.lineTo(top[i].x, top[i].y)
        }
        // Close along bottom edge in reverse
        for (let i = bottom.length - 1; i >= 0; i--) {
            ctx.lineTo(bottom[i].x, bottom[i].y)
        }
        ctx.closePath()
        ctx.fill()
    }

    ctx.globalAlpha = 1
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
