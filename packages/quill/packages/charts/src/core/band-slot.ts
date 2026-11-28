import { type BarScaleSet, groupedBandSlot } from './scales'
import type { BandSlot } from './types'

/** Resolve only the band-axis extent of a (series, label) slot: the whole band for a single
 *  series, the series' sub-band when grouped. Cheap — touches the band and group scales and
 *  nothing on the value axis — so band-only hit-testing doesn't pay for value-axis lookups it
 *  would throw away. Shared by the chart types that draw one shape per band (box and violin). */
export function computeBandSlot(
    seriesKey: string,
    label: string,
    scales: BarScaleSet,
    grouped: boolean
): BandSlot | null {
    if (grouped) {
        return groupedBandSlot(scales, label, seriesKey) ?? null
    }
    const bandStart = scales.band(label)
    if (bandStart == null) {
        return null
    }
    return { x: bandStart, width: scales.band.bandwidth() }
}

/** Whether the cursor lies inside the band-axis extent of a slot. Mirrors the bar-chart pattern
 *  of resolving "which sub-band is under the cursor" with a value-axis-agnostic check, so hovering
 *  above or below a tall shape still selects it. */
export function cursorInsideBandSlot(slot: BandSlot, cursor: { x: number; y: number }, horizontal = false): boolean {
    const bandCoord = horizontal ? cursor.y : cursor.x
    return bandCoord >= slot.x && bandCoord <= slot.x + slot.width
}

/** The part of a series the band hit-test reads: its key, one entry per label (`null`/`undefined`
 *  where it has no shape), and whether it is hidden. */
interface BandHitSeries {
    key: string
    data: readonly unknown[]
    visibility?: { excluded?: boolean }
}

export interface SeriesKeysAtCursorArgs {
    series: readonly BandHitSeries[]
    label: string
    dataIndex: number
    cursor: { x: number; y: number }
    scales: BarScaleSet
    grouped: boolean
    /** Bands run along y instead of x. */
    horizontal?: boolean
}

/** Returns the set of series keys whose shape (at the given x-label) contains the cursor on the
 *  band axis. An empty set means the cursor sits in a gap between groups — the tooltip wrapper uses
 *  that to hide the tooltip rather than highlight all neighbouring series. Uses `computeBandSlot`
 *  (band-axis only) — value-axis math is for the highlight pass, not the hit-test. */
export function seriesKeysAtCursor(args: SeriesKeysAtCursorArgs): Set<string> {
    const { series, label, dataIndex, cursor, scales, grouped, horizontal = false } = args
    const hits = new Set<string>()
    for (const s of series) {
        if (s.visibility?.excluded || !s.data[dataIndex]) {
            continue
        }
        const slot = computeBandSlot(s.key, label, scales, grouped)
        if (slot && cursorInsideBandSlot(slot, cursor, horizontal)) {
            hits.add(s.key)
        }
    }
    return hits
}
