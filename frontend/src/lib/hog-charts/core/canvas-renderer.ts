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
    const { ctx, xScale, yScale, labels } = drawCtx
    const data = yValues ?? series.data

    if (data.length === 0) {
        return
    }

    ctx.beginPath()
    ctx.strokeStyle = series.color
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.setLineDash(series.dashPattern ?? [])

    let started = false
    for (let i = 0; i < data.length; i++) {
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

export function drawArea(drawCtx: DrawContext, series: Series, yValues?: number[]): void {
    const { ctx, xScale, yScale, labels, dimensions } = drawCtx
    const data = yValues ?? series.data
    const opacity = series.fillOpacity ?? 0.5
    const baseline = dimensions.plotTop + dimensions.plotHeight

    // Split into contiguous segments to handle data gaps consistently with drawLine
    const segments: { x: number; y: number }[][] = []
    let current: { x: number; y: number }[] = []
    for (let i = 0; i < data.length; i++) {
        const x = xScale(labels[i])
        const y = yScale(data[i])
        if (x != null && isFinite(y)) {
            current.push({ x, y })
        } else if (current.length > 0) {
            segments.push(current)
            current = []
        }
    }
    if (current.length > 0) {
        segments.push(current)
    }

    ctx.globalAlpha = opacity
    ctx.fillStyle = series.color

    for (const points of segments) {
        if (points.length < 2) {
            continue
        }
        ctx.beginPath()
        ctx.moveTo(points[0].x, points[0].y)
        for (let i = 1; i < points.length; i++) {
            ctx.lineTo(points[i].x, points[i].y)
        }
        ctx.lineTo(points[points.length - 1].x, baseline)
        ctx.lineTo(points[0].x, baseline)
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
