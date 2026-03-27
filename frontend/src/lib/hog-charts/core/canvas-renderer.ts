import * as d3 from 'd3'

import type { ChartDimensions, Series } from './types'

export interface DrawContext {
    ctx: CanvasRenderingContext2D
    dimensions: ChartDimensions
    xScale: d3.ScalePoint<string>
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    labels: string[]
}

/** Draw a single series line. Batches into one beginPath/stroke for performance. */
export function drawLine(
    drawCtx: DrawContext,
    series: Series,
    yValues?: number[],
    options?: {
        incompleteFromIndex?: number
    }
): void {
    const { ctx, xScale, yScale, labels } = drawCtx
    const data = yValues ?? series.data

    if (data.length === 0) {
        return
    }

    const incompleteFrom = options?.incompleteFromIndex ?? data.length

    // Draw solid portion
    if (incompleteFrom > 0) {
        ctx.beginPath()
        ctx.strokeStyle = series.color
        ctx.lineWidth = 2
        ctx.lineJoin = 'round'
        ctx.lineCap = 'round'

        if (series.dashPattern && !options?.incompleteFromIndex) {
            ctx.setLineDash(series.dashPattern)
        } else {
            ctx.setLineDash([])
        }

        let started = false
        const end = Math.min(incompleteFrom, data.length)
        for (let i = 0; i < end; i++) {
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
        ctx.setLineDash([])
    }

    // Draw incomplete (dashed) portion
    if (incompleteFrom < data.length) {
        ctx.beginPath()
        ctx.strokeStyle = series.color
        ctx.lineWidth = 2
        ctx.lineJoin = 'round'
        ctx.lineCap = 'round'
        ctx.setLineDash([6, 4])

        // Start from the last complete point for continuity
        const startIdx = Math.max(0, incompleteFrom - 1)
        let started = false
        for (let i = startIdx; i < data.length; i++) {
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
        ctx.setLineDash([])
    }
}

/** Draw area fill under a series line. */
export function drawArea(
    drawCtx: DrawContext,
    series: Series,
    yValues?: number[],
    options?: {
        incompleteFromIndex?: number
    }
): void {
    const { ctx, xScale, yScale, labels, dimensions } = drawCtx
    const data = yValues ?? series.data
    const opacity = series.fillOpacity ?? 0.5
    const baseline = dimensions.plotTop + dimensions.plotHeight
    const incompleteFrom = options?.incompleteFromIndex ?? data.length

    // Solid area fill
    if (incompleteFrom > 0) {
        drawAreaSegment(
            ctx,
            xScale,
            yScale,
            labels,
            data,
            0,
            Math.min(incompleteFrom, data.length),
            series.color,
            opacity,
            baseline
        )
    }

    // Pinstripe area fill for incomplete data
    if (incompleteFrom < data.length) {
        const startIdx = Math.max(0, incompleteFrom - 1)
        drawAreaSegment(
            ctx,
            xScale,
            yScale,
            labels,
            data,
            startIdx,
            data.length,
            series.color,
            opacity * 0.5,
            baseline,
            true
        )
    }
}

function drawAreaSegment(
    ctx: CanvasRenderingContext2D,
    xScale: d3.ScalePoint<string>,
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>,
    labels: string[],
    data: number[],
    startIdx: number,
    endIdx: number,
    color: string,
    opacity: number,
    baseline: number,
    pinstripe: boolean = false
): void {
    const points: { x: number; y: number }[] = []
    for (let i = startIdx; i < endIdx; i++) {
        const x = xScale(labels[i])
        const y = yScale(data[i])
        if (x != null && isFinite(y)) {
            points.push({ x, y })
        }
    }

    if (points.length < 2) {
        return
    }

    ctx.beginPath()
    ctx.moveTo(points[0].x, points[0].y)
    for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y)
    }
    ctx.lineTo(points[points.length - 1].x, baseline)
    ctx.lineTo(points[0].x, baseline)
    ctx.closePath()

    if (pinstripe) {
        ctx.save()
        ctx.clip()
        ctx.globalAlpha = opacity
        ctx.fillStyle = color
        // Draw diagonal pinstripes
        const step = 6
        const maxDim = Math.max(ctx.canvas.width, ctx.canvas.height) * 2
        ctx.lineWidth = 1
        ctx.strokeStyle = color
        for (let offset = -maxDim; offset < maxDim; offset += step) {
            ctx.beginPath()
            ctx.moveTo(offset, 0)
            ctx.lineTo(offset + maxDim, maxDim)
            ctx.stroke()
        }
        ctx.restore()
    } else {
        ctx.globalAlpha = opacity
        ctx.fillStyle = color
        ctx.fill()
    }

    ctx.globalAlpha = 1
}

/** Draw data point dots for a series. */
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

/** Draw grid lines on the canvas. */
export function drawGrid(
    drawCtx: DrawContext,
    options: {
        gridColor?: string
        goalLineValues?: number[]
    } = {}
): void {
    const { ctx, yScale, dimensions } = drawCtx
    const gridColor = options.gridColor ?? 'rgba(0, 0, 0, 0.1)'
    const goalValues = new Set(options.goalLineValues ?? [])

    const yTicks = (yScale as d3.ScaleLinear<number, number>).ticks?.() ?? []

    ctx.strokeStyle = gridColor
    ctx.lineWidth = 1
    ctx.setLineDash([])

    for (const tick of yTicks) {
        // Make grid lines transparent where goal lines intersect
        if (goalValues.has(tick)) {
            continue
        }
        const y = Math.round(yScale(tick)) + 0.5
        ctx.beginPath()
        ctx.moveTo(dimensions.plotLeft, y)
        ctx.lineTo(dimensions.plotLeft + dimensions.plotWidth, y)
        ctx.stroke()
    }
}

/** Draw a highlighted point (for hover). */
export function drawHighlightPoint(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    color: string,
    radius: number = 4
): void {
    // Outer ring (white border)
    ctx.fillStyle = '#ffffff'
    ctx.beginPath()
    ctx.arc(x, y, radius + 2, 0, Math.PI * 2)
    ctx.fill()

    // Inner colored dot
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    ctx.fill()
}
