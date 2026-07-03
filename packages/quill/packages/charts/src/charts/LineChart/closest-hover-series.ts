import type { ResolvedSeries } from '../../core/types'

/**
 * Of the visible series, the key whose y-pixel at the hovered index sits closest to the cursor —
 * so a multi-series line chart draws a single hover dot on the line under the cursor instead of a
 * column of rings across every series.
 *
 * Excluded series (legend-hidden), fill-between lower bounds, and overlays (moving averages, trend
 * lines, goal lines) are never candidates: in percent-stack mode their raw values ring far off-plot,
 * and they aren't the line the user is pointing at. `yPixelFor` returns a series' y-pixel at the
 * hovered index; a non-finite y skips that series. Returns null when no series qualifies.
 */
export function closestHoverSeriesKey(
    series: readonly ResolvedSeries[],
    yPixelFor: (series: ResolvedSeries) => number,
    cursorY: number
): string | null {
    let closestKey: string | null = null
    let minDist = Infinity
    for (const s of series) {
        if (s.visibility?.excluded || s.fill?.lowerData || s.overlay) {
            continue
        }
        const y = yPixelFor(s)
        if (Number.isFinite(y)) {
            const dist = Math.abs(y - cursorY)
            if (dist < minDist) {
                minDist = dist
                closestKey = s.key
            }
        }
    }
    return closestKey
}
