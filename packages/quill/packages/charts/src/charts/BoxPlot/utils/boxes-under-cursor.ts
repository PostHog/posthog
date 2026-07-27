import type { BarScaleSet } from '../../../core/scales'
import { computeBoxBand } from '../computeBoxLayout'
import type { BoxPlotSeries } from '../types'

/** Whether the cursor lies inside the band-axis extent of a box. Mirrors the
 *  bar-chart pattern of resolving "which sub-band is under the cursor" with a
 *  value-axis-agnostic check, so hovering above (or below) a tall whisker still
 *  selects the right box. */
export function cursorInsideBoxBand(box: { x: number; width: number }, cursor: { x: number }): boolean {
    return cursor.x >= box.x && cursor.x <= box.x + box.width
}

export interface SeriesKeysAtCursorArgs<Meta> {
    series: BoxPlotSeries<Meta>[]
    label: string
    dataIndex: number
    cursor: { x: number; y: number }
    scales: BarScaleSet
    grouped: boolean
}

/** Returns the set of series keys whose box (at the given x-label) contains the cursor
 *  on the band axis. Empty set means the cursor sits in a gap between groups — the
 *  tooltip wrapper uses that to hide the tooltip rather than highlight all neighbouring
 *  series. Uses `computeBoxBand` (band-axis only) — value-axis math is for the highlight
 *  pass, not the hit-test. */
export function seriesKeysAtCursor<Meta>(args: SeriesKeysAtCursorArgs<Meta>): Set<string> {
    const { series, label, dataIndex, cursor, scales, grouped } = args
    const hits = new Set<string>()
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const datum = s.data[dataIndex]
        if (!datum) {
            continue
        }
        const band = computeBoxBand(s.key, label, scales, grouped)
        if (band && cursorInsideBoxBand(band, cursor)) {
            hits.add(s.key)
        }
    }
    return hits
}
