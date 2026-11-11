import type { ChartDimensions, ChartMargins } from './types'

/** The subset of `DOMRect` the canvas sizing needs. */
export interface SizeRect {
    width: number
    height: number
}

const MAX_CANVAS_SIDE = 32767

/** `canvas.width`/`height` are integers, so a fractional target has to be rounded before it's
 *  compared or assigned — otherwise it never equals the stored value and every sync reads as a
 *  change. */
function backingSize(cssSize: number, dpr: number): number {
    return Math.round(cssSize * dpr)
}

/** Size a canvas to `rect` at `dpr`, touching `width`/`height` only when they actually change.
 *  Returns whether the backing store was reallocated — i.e. whether the bitmap was wiped and a
 *  repaint is now mandatory.
 *
 *  Assigning `canvas.width` or `canvas.height` resets the bitmap to transparent black and
 *  reallocates it, even when the assigned value is identical to the current one. Callers sync on
 *  every paint, so a redundant assignment would reallocate the bitmap on every frame. */
export function syncCanvasSize(canvas: HTMLCanvasElement, rect: SizeRect, dpr: number): boolean {
    // Chromium and Firefox paint nothing into a canvas with a side over 32,767 backing pixels. A
    // very tall chart (a retention grid with hundreds of cohorts) lowers its ratio to stay under
    // that side, so it draws less sharply instead of blank. Draw code reads the ratio back off
    // the backing size, so it follows. ponytail: one canvas per chart; above 32,767 css px the
    // ratio drops below 1 and blurs, and only splitting the canvas into tiles avoids that.
    dpr = Math.min(dpr, MAX_CANVAS_SIDE / Math.max(rect.width, rect.height))
    const width = backingSize(rect.width, dpr)
    const height = backingSize(rect.height, dpr)
    let resized = false
    if (canvas.width !== width) {
        canvas.width = width
        resized = true
    }
    if (canvas.height !== height) {
        canvas.height = height
        resized = true
    }
    const cssWidth = `${rect.width}px`
    const cssHeight = `${rect.height}px`
    if (canvas.style.width !== cssWidth) {
        canvas.style.width = cssWidth
    }
    if (canvas.style.height !== cssHeight) {
        canvas.style.height = cssHeight
    }
    return resized
}

// `Math.max(0, NaN)` is `NaN`, not `0` — so a single non-finite input (an unmeasured container, a
// NaN margin) would silently poison the plot size. A NaN `plotWidth`/`plotHeight` flows straight
// into the value-scale pixel range, mapping every point and axis tick to NaN: the chart paints
// nothing while x-only pointer hit-testing still fires tooltips. Floor to a finite, non-negative size.
function finitePlotSize(size: number): number {
    return isFinite(size) && size > 0 ? size : 0
}

export function buildDimensions(rect: SizeRect, margins: ChartMargins): ChartDimensions {
    return {
        width: rect.width,
        height: rect.height,
        plotLeft: margins.left,
        plotTop: margins.top,
        plotWidth: finitePlotSize(rect.width - margins.left - margins.right),
        plotHeight: finitePlotSize(rect.height - margins.top - margins.bottom),
    }
}

export function sameDimensions(a: ChartDimensions, b: ChartDimensions): boolean {
    return (
        a.width === b.width &&
        a.height === b.height &&
        a.plotLeft === b.plotLeft &&
        a.plotTop === b.plotTop &&
        a.plotWidth === b.plotWidth &&
        a.plotHeight === b.plotHeight
    )
}
