import type { ChartDimensions } from '../types'

/** Reset the transform to device-pixel scale and clear the whole canvas, leaving the ctx in a
 *  saved state the caller restores after drawing. Shared by the static and hover draw loops. */
export function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): void {
    const dpr = window.devicePixelRatio || 1
    ctx.save()
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, dimensions.width, dimensions.height)
}
