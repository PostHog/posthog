import type { ChartDimensions } from '../types'

/** Reset the transform to device-pixel scale and clear the whole canvas, leaving the ctx in a
 *  saved state the caller restores after drawing. Shared by the static and hover draw loops.
 *
 *  The scale is derived from the backing store the canvas was actually sized with
 *  (`canvas.width / dimensions.width`, and the same for height) rather than a fresh
 *  `window.devicePixelRatio` read. Each axis gets its own ratio: `syncCanvasSize` rounds each side,
 *  and on a capped tall canvas one shared ratio drifts the far rows by tens of pixels. A
 *  redraw can run at a different devicePixelRatio than the one that sized the backing (e.g. a
 *  headless export that resizes the viewport under device_scale_factor=2); reading it again here
 *  would scale the transform inconsistently with the canvas and magnify/clip the drawing. */
export function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): void {
    const fallback = window.devicePixelRatio || 1
    const scaleX = dimensions.width > 0 ? ctx.canvas.width / dimensions.width : fallback
    const scaleY = dimensions.height > 0 ? ctx.canvas.height / dimensions.height : fallback
    ctx.save()
    ctx.setTransform(scaleX, 0, 0, scaleY, 0, 0)
    ctx.clearRect(0, 0, dimensions.width, dimensions.height)
}
