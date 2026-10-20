import { syncCanvasSize } from '../canvas-size'
import type { ChartDimensions } from '../types'

/** Size the backing store to `dimensions`, reset the transform to device-pixel scale, and clear
 *  the whole canvas, leaving the ctx in a saved state the caller restores after drawing. Shared by
 *  the static and hover draw loops.
 *
 *  The resize happens here, in the same frame as the repaint, because a resize wipes the bitmap.
 *  Until the draw loop runs, the canvas keeps showing the last frame.
 *
 *  The scale is derived from the backing store (`canvas.width / dimensions.width`), so the
 *  transform always matches the rounded integer size the canvas actually has. */
export function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): void {
    syncCanvasSize(ctx.canvas, dimensions, window.devicePixelRatio || 1)
    const dpr = dimensions.width > 0 ? ctx.canvas.width / dimensions.width : window.devicePixelRatio || 1
    ctx.save()
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, dimensions.width, dimensions.height)
}
