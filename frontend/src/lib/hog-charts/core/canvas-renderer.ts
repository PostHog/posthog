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
