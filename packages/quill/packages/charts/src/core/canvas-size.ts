import type { ChartDimensions, ChartMargins } from './types'

/** The subset of `DOMRect` the canvas sizing needs. */
export interface SizeRect {
    width: number
    height: number
}

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
 *  Assigning `canvas.width` or `canvas.height` resets the bitmap to transparent black — even when
 *  the assigned value is identical to the current one. The draw loops repaint on the *next*
 *  animation frame, so every redundant assignment costs one fully blank painted frame, and a
 *  container that keeps reporting resizes (a scrollbar appearing and disappearing on an
 *  `overflow: auto` ancestor, an animating panel) wipes the bitmap faster than it is repainted —
 *  the chart reads as blank while its DOM axis labels keep rendering. `ResizeObserver` also
 *  delivers an initial observation on top of the synchronous first measure, so the redundant case
 *  happens on every mount. */
export function syncCanvasSize(canvas: HTMLCanvasElement, rect: SizeRect, dpr: number): boolean {
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

export function buildDimensions(rect: SizeRect, margins: ChartMargins): ChartDimensions {
    return {
        width: rect.width,
        height: rect.height,
        plotLeft: margins.left,
        plotTop: margins.top,
        plotWidth: Math.max(0, rect.width - margins.left - margins.right),
        plotHeight: Math.max(0, rect.height - margins.top - margins.bottom),
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
