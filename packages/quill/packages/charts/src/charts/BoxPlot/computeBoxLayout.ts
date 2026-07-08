import { type BarScaleSet, groupedBandSlot } from '../../core/scales'
import type { BandSlot, BoxRect } from '../../core/types'
import type { BoxPlotDatum } from './types'

/** Resolve only the band-axis extent of a (series, x) slot. Cheap — touches the band/group
 *  scales and nothing on the value axis — so callers like band-only hit-testing don't pay
 *  for six value-axis lookups they'd immediately throw away. */
export function computeBoxBand(
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

export interface ComputeBoxRectOptions {
    seriesKey: string
    label: string
    dataIndex: number
    datum: BoxPlotDatum
    scales: BarScaleSet
    /** Whether the chart is in grouped mode (multiple series → side-by-side boxes within a band). */
    grouped: boolean
}

/** Single-box geometry. Pure: takes already-built scales and returns pixel coordinates only.
 *  Returns `null` when any of (band, group offset, value pixel) can't be resolved — usually
 *  the series isn't in the group scale, or one of the six numbers is non-finite. */
export function computeBoxRect({
    seriesKey,
    label,
    dataIndex,
    datum,
    scales,
    grouped,
}: ComputeBoxRectOptions): BoxRect | null {
    if (
        !Number.isFinite(datum.min) ||
        !Number.isFinite(datum.max) ||
        !Number.isFinite(datum.p25) ||
        !Number.isFinite(datum.p75)
    ) {
        return null
    }
    if (!Number.isFinite(datum.median) || !Number.isFinite(datum.mean)) {
        return null
    }
    const slot = computeBoxBand(seriesKey, label, scales, grouped)
    if (!slot) {
        return null
    }

    const p25Y = scales.value(datum.p25)
    const p75Y = scales.value(datum.p75)
    const medianY = scales.value(datum.median)
    const meanY = scales.value(datum.mean)
    const maxY = scales.value(datum.max)
    const minY = scales.value(datum.min)
    if (!Number.isFinite(p25Y) || !Number.isFinite(p75Y) || !Number.isFinite(medianY) || !Number.isFinite(meanY)) {
        return null
    }
    if (!Number.isFinite(maxY) || !Number.isFinite(minY)) {
        return null
    }

    // y-axis is inverted (larger value = smaller pixel) — `top` is the p75 pixel
    // when p75 >= p25 (the normal case), but be defensive against degenerate input.
    const top = Math.min(p25Y, p75Y)
    const bottom = Math.max(p25Y, p75Y)
    const whiskerTop = Math.min(minY, maxY)
    const whiskerBottom = Math.max(minY, maxY)

    return {
        x: slot.x,
        width: slot.width,
        top,
        bottom,
        medianY,
        mean: { x: slot.x + slot.width / 2, y: meanY },
        whiskerTop,
        whiskerBottom,
        dataIndex,
    }
}

export interface ComputeSeriesBoxesOptions {
    seriesKey: string
    data: (BoxPlotDatum | null)[]
    labels: string[]
    scales: BarScaleSet
    grouped: boolean
}

/** Lays out every renderable box for one series. Skipped indices (`null` datum or
 *  unresolvable scales) are dropped from the result — the caller can join back to the
 *  original `data` via `BoxRect.dataIndex`. */
export function computeSeriesBoxes({ seriesKey, data, labels, scales, grouped }: ComputeSeriesBoxesOptions): BoxRect[] {
    const out: BoxRect[] = []
    const len = Math.min(data.length, labels.length)
    for (let i = 0; i < len; i++) {
        const datum = data[i]
        if (!datum) {
            continue
        }
        const rect = computeBoxRect({
            seriesKey,
            label: labels[i],
            dataIndex: i,
            datum,
            scales,
            grouped,
        })
        if (rect) {
            out.push(rect)
        }
    }
    return out
}
