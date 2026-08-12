import { traceScatterMarker } from '../../core/canvas-renderer'
import { dimColor } from '../../core/color-utils'
import type { ScatterPointPosition } from './scatter-layout'

const MARKER_STROKE_WIDTH = 1.25
const HOVER_HALO_WIDTH = 3
const HOVER_HALO_RADIUS_PX = 2

/** Fills translucent and strokes opaque, so an overlapping cloud reads as density while each marker
 *  keeps a crisp edge. A `cross` is strokes only, so it skips the fill. */
export function drawScatterMarkers(
    ctx: CanvasRenderingContext2D,
    positions: ScatterPointPosition[],
    fillOpacity: number
): void {
    const fills = new Map<string, string>()
    ctx.save()
    ctx.lineWidth = MARKER_STROKE_WIDTH
    for (const position of positions) {
        traceScatterMarker(ctx, position.shape, position.x, position.y, position.radius)
        if (position.shape !== 'cross') {
            let fill = fills.get(position.color)
            if (fill === undefined) {
                fill = dimColor(position.color, fillOpacity)
                fills.set(position.color, fill)
            }
            ctx.fillStyle = fill
            ctx.fill()
        }
        ctx.strokeStyle = position.color
        ctx.stroke()
    }
    ctx.restore()
}

export function drawScatterHoverMarker(
    ctx: CanvasRenderingContext2D,
    position: ScatterPointPosition,
    backgroundColor: string,
    alpha: number
): void {
    ctx.save()
    ctx.globalAlpha = alpha
    ctx.lineWidth = HOVER_HALO_WIDTH
    ctx.strokeStyle = backgroundColor
    traceScatterMarker(ctx, position.shape, position.x, position.y, position.radius + HOVER_HALO_RADIUS_PX)
    ctx.stroke()
    ctx.lineWidth = MARKER_STROKE_WIDTH
    ctx.strokeStyle = position.color
    ctx.fillStyle = position.color
    traceScatterMarker(ctx, position.shape, position.x, position.y, position.radius)
    if (position.shape !== 'cross') {
        ctx.fill()
    }
    ctx.stroke()
    ctx.restore()
}
