import type { BarScaleSet } from '../../../core/scales'
import { computeBoxRect } from '../computeBoxLayout'
import type { BoxPlotSeries } from '../computeBoxLayout'

/** Whether the cursor lies inside the band-axis extent of a box. Mirrors the
 *  bar-chart pattern of resolving "which sub-band is under the cursor" with a
 *  value-axis-agnostic check, so hovering above (or below) a tall whisker still
 *  selects the right box. */
export function cursorInsideBoxBand(box: { x: number; width: number }, cursor: { x: number }): boolean {
    return cursor.x >= box.x && cursor.x <= box.x + box.width
}

/** Whether the cursor lies fully inside the painted box rect (both band and value axes).
 *  Useful for distinguishing "over the box body" from "over a whisker" if a caller wants
 *  finer-grained highlighting. */
export function cursorInsideBoxRect(
    box: { x: number; width: number; top: number; bottom: number },
    cursor: { x: number; y: number }
): boolean {
    return cursor.x >= box.x && cursor.x <= box.x + box.width && cursor.y >= box.top && cursor.y <= box.bottom
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
 *  series. */
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
        const box = computeBoxRect({
            seriesKey: s.key,
            label,
            dataIndex,
            datum,
            scales,
            grouped,
        })
        if (box && cursorInsideBoxBand(box, cursor)) {
            hits.add(s.key)
        }
    }
    return hits
}

/** Finds the single nearest box to a cursor — index into the *filtered hits* whose box
 *  center is closest on the band axis. Returns -1 if the input set is empty. Used by the
 *  hover layer to pick one box to highlight when the band-axis hit narrowed to several
 *  candidates (e.g. wide grouped slots that overlap due to negative padding). */
export function nearestBoxIndex(boxes: { x: number; width: number }[], cursor: { x: number }): number {
    if (boxes.length === 0) {
        return -1
    }
    let best = -1
    let bestDist = Infinity
    for (let i = 0; i < boxes.length; i++) {
        const center = boxes[i].x + boxes[i].width / 2
        const dist = Math.abs(cursor.x - center)
        if (dist < bestDist) {
            bestDist = dist
            best = i
        }
    }
    return best
}
