import { syncCanvasSize } from '../canvas-size'
import type { ChartDimensions } from '../types'

/** Size the backing store to `dimensions`, reset the transform to device-pixel scale, and clear
 *  the whole canvas, leaving the ctx in a saved state the caller restores after drawing. Shared by
 *  the static and hover draw loops.
 *
 *  The resize happens here, in the same frame as the repaint, because a resize wipes the bitmap.
 *  Until the draw loop runs, the canvas keeps showing the last frame.
 *
 *  The scale is derived from the backing store (`canvas.width / dimensions.width`, and the same
 *  for height), so the transform always matches the rounded integer size the canvas actually has.
 *  Each axis gets its own ratio: `syncCanvasSize` rounds each side, and on a capped tall canvas
 *  one shared ratio drifts the far rows by tens of pixels. */
export function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): void {
    const fallback = window.devicePixelRatio || 1
    syncCanvasSize(ctx.canvas, dimensions, fallback)
    const scaleX = dimensions.width > 0 ? ctx.canvas.width / dimensions.width : fallback
    const scaleY = dimensions.height > 0 ? ctx.canvas.height / dimensions.height : fallback
    ctx.save()
    ctx.setTransform(scaleX, 0, 0, scaleY, 0, 0)
    ctx.clearRect(0, 0, dimensions.width, dimensions.height)
}
