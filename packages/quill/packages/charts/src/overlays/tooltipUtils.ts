/** Returns the key of the series whose canvas y-pixel is closest to `cursorY`.
 *  Returns `null` when no entry carries `yPixel` data. */
export function findClosestSeriesKey(
    rows: Array<{ series: { key: string }; yPixel?: number }>,
    cursorY: number
): string | null {
    let bestKey: string | null = null
    let bestDist = Infinity
    for (const s of rows) {
        if (s.yPixel == null) {
            continue
        }
        const dist = Math.abs(s.yPixel - cursorY)
        if (dist < bestDist) {
            bestDist = dist
            bestKey = s.series.key
        }
    }
    return bestKey
}
