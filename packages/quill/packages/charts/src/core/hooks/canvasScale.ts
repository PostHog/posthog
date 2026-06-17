// Browsers reject canvas backing stores past a per-dimension and a total-area limit; exceeding
// either puts the canvas in a permanent error state, so every later `setTransform`/`clearRect`
// throws. Chrome caps each side at 16384px and the area at 16384², Safari allows wider sides but
// a smaller area — clamping to the Chrome limits keeps us safe everywhere.
const MAX_CANVAS_DIMENSION = 16384
const MAX_CANVAS_AREA = MAX_CANVAS_DIMENSION * MAX_CANVAS_DIMENSION

/**
 * The device-pixel scale to back a `cssWidth × cssHeight` canvas with, clamped so the resulting
 * bitmap never exceeds the browser's per-dimension or total-area limits. Returns `dpr` unchanged
 * for ordinary sizes; for very large wrappers or high `devicePixelRatio` it returns a smaller
 * scale (the chart renders at reduced resolution rather than crashing). `sizeCanvas` and
 * `clearAndPrepare` both derive the transform from this, so the backing store and the draw
 * transform always agree.
 */
export function effectiveCanvasScale(cssWidth: number, cssHeight: number, dpr: number): number {
    const baseScale = dpr > 0 ? dpr : 1
    if (cssWidth <= 0 || cssHeight <= 0) {
        return baseScale
    }
    let scale = Math.min(baseScale, MAX_CANVAS_DIMENSION / cssWidth, MAX_CANVAS_DIMENSION / cssHeight)
    if (cssWidth * cssHeight * scale * scale > MAX_CANVAS_AREA) {
        scale = Math.sqrt(MAX_CANVAS_AREA / (cssWidth * cssHeight))
    }
    // Stay strictly positive — a 0 scale would collapse the backing store to nothing.
    return Math.max(scale, Number.MIN_VALUE)
}
