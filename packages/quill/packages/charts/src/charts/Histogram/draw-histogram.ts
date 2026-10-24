import { SELECTION_FILL, SELECTION_STROKE } from '../../core/canvas-renderer'
import type { HistogramLayout, HistogramSegment } from '../../core/histogram-layout'
import type { ChartDimensions } from '../../core/types'

/** Bars outside a selection fade to this alpha so the selected range reads as the subject. */
export const OUTSIDE_SELECTION_ALPHA = 0.35
const HOVER_COLUMN_ALPHA = 0.08

export function drawHistogramBars(
    ctx: CanvasRenderingContext2D,
    segments: HistogramSegment[],
    colors: string[],
    isDimmed?: (column: number) => boolean
): void {
    for (const segment of segments) {
        ctx.globalAlpha = isDimmed?.(segment.column) ? OUTSIDE_SELECTION_ALPHA : 1
        ctx.fillStyle = colors[segment.seriesIndex]
        ctx.fillRect(segment.x, segment.y, segment.width, segment.height)
    }
    ctx.globalAlpha = 1
}

/** The selection band, in the live drag band's color so releasing a drag leaves it in place. Drawn
 *  before the bars, so the selected bars keep their own color. */
export function drawHistogramSelectionBand(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    span: { x0: number; x1: number }
): void {
    ctx.fillStyle = SELECTION_FILL
    ctx.fillRect(span.x0, dimensions.plotTop, span.x1 - span.x0, dimensions.plotHeight)
}

/** The selection's two edges, drawn over the bars. */
export function drawHistogramSelectionEdges(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    span: { x0: number; x1: number }
): void {
    ctx.strokeStyle = SELECTION_STROKE
    ctx.lineWidth = 1
    ctx.setLineDash([])
    ctx.beginPath()
    for (const x of [span.x0, span.x1]) {
        const crisp = Math.round(x) + 0.5
        ctx.moveTo(crisp, dimensions.plotTop)
        ctx.lineTo(crisp, dimensions.plotTop + dimensions.plotHeight)
    }
    ctx.stroke()
}

/** A faint column marks which bin the tooltip describes, empty bins included, and the bin's
 *  segments darken the way a hovered bar does on the bar charts. */
export function drawHistogramHover(
    ctx: CanvasRenderingContext2D,
    layout: HistogramLayout,
    dimensions: ChartDimensions,
    binIndex: number,
    hoverColors: string[],
    columnColor: string,
    progress: number
): boolean {
    const column = layout.bins[layout.columnOf[binIndex] ?? -1]
    if (!column) {
        return false
    }
    ctx.globalAlpha = HOVER_COLUMN_ALPHA * progress
    ctx.fillStyle = columnColor
    ctx.fillRect(column.x0, dimensions.plotTop, column.x1 - column.x0, dimensions.plotHeight)
    ctx.globalAlpha = progress
    for (let i = column.segmentStart; i < column.segmentEnd; i++) {
        const segment = layout.segments[i]
        ctx.fillStyle = hoverColors[segment.seriesIndex]
        ctx.fillRect(segment.x, segment.y, segment.width, segment.height)
    }
    ctx.globalAlpha = 1
    return true
}
