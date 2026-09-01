/** Returns the key of the series whose segment contains `cursorY`, or the closest one by distance.
 *
 * When `yPixelBottom` is present alongside `yPixel` (stacked bar segments), uses range
 * containment: the series whose [top, bottom] range contains the cursor wins outright. This is
 * exact regardless of segment size differences — no midpoint dead-zones at boundaries.
 *
 * When only `yPixel` is present (line dots, non-stacked bars), falls back to closest by distance.
 * Distance ties go to the last tied row: equal-valued lines sit exactly on top of each other and
 * paint in array order, so the last one is the visible line. This matches the hover dot's own
 * tie-breaking, keeping the highlighted tooltip row and the dot on the same series.
 */
export function findClosestSeriesKey(
    rows: Array<{ series: { key: string }; yPixel?: number; yPixelBottom?: number }>,
    cursorY: number
): string | null {
    // Range containment pass — exact for stacked segments.
    for (const s of rows) {
        if (s.yPixel != null && s.yPixelBottom != null) {
            const lo = Math.min(s.yPixel, s.yPixelBottom)
            const hi = Math.max(s.yPixel, s.yPixelBottom)
            if (cursorY >= lo && cursorY <= hi) {
                return s.series.key
            }
        }
    }
    // Distance fallback for lines, dots, and non-stacked bars.
    let bestKey: string | null = null
    let bestDist = Infinity
    for (const s of rows) {
        if (s.yPixel == null) {
            continue
        }
        const dist = Math.abs(s.yPixel - cursorY)
        if (dist <= bestDist) {
            bestDist = dist
            bestKey = s.series.key
        }
    }
    return bestKey
}
