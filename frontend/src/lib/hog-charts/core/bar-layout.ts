import type { BarRect, BarRoundedCorners } from './canvas-renderer'
import type { BarScaleSet, StackedBand } from './scales'
import type { Series } from './types'

export type SeriesBarLayout = (BarRect | null)[]

/** Cap is the side away from the value-axis baseline; pass `shouldRoundCap: false` for stacked
 *  layers below the topmost. */
export function cornersFor(isHorizontal: boolean, isPositive: boolean, shouldRoundCap: boolean): BarRoundedCorners {
    if (!shouldRoundCap) {
        return {}
    }
    if (isHorizontal) {
        return isPositive ? { topRight: true, bottomRight: true } : { topLeft: true, bottomLeft: true }
    }
    return isPositive ? { topLeft: true, topRight: true } : { bottomLeft: true, bottomRight: true }
}

function makeBarRect(
    isHorizontal: boolean,
    bandStart: number,
    bandSize: number,
    valueA: number,
    valueB: number,
    corners: BarRoundedCorners,
    dataIndex: number
): BarRect {
    const valueMin = Math.min(valueA, valueB)
    const valueSize = Math.abs(valueA - valueB)
    return isHorizontal
        ? { x: valueMin, y: bandStart, width: valueSize, height: bandSize, corners, dataIndex }
        : { x: bandStart, y: valueMin, width: bandSize, height: valueSize, corners, dataIndex }
}

export interface ComputeSeriesBarsOptions {
    series: Series
    labels: string[]
    scales: BarScaleSet
    layout: 'stacked' | 'grouped' | 'percent'
    isHorizontal: boolean
    /** Required for `stacked` and `percent` layouts. Must be omitted for `grouped`. */
    stackedBand?: StackedBand
    isTopOfStack: boolean
}

export function computeSeriesBars({
    series,
    labels,
    scales,
    layout,
    isHorizontal,
    stackedBand,
    isTopOfStack,
}: ComputeSeriesBarsOptions): SeriesBarLayout {
    const result: SeriesBarLayout = new Array(labels.length)
    for (let i = 0; i < labels.length; i++) {
        result[i] = computeBarAtIndex({
            series,
            label: labels[i],
            dataIndex: i,
            scales,
            layout,
            isHorizontal,
            stackedBand,
            isTopOfStack,
        })
    }
    return result
}

export interface ComputeBarAtIndexOptions {
    series: Series
    label: string
    dataIndex: number
    scales: BarScaleSet
    layout: 'stacked' | 'grouped' | 'percent'
    isHorizontal: boolean
    /** Required for `stacked` and `percent` layouts. Must be omitted for `grouped`. */
    stackedBand?: StackedBand
    isTopOfStack: boolean
}

/** Single-bar fast path for `drawHover` so the overlay redraw doesn't recompute every bar
 *  on every mousemove. Returns `null` for indices with no renderable bar. */
export function computeBarAtIndex({
    series,
    label,
    dataIndex,
    scales,
    layout,
    isHorizontal,
    stackedBand,
    isTopOfStack,
}: ComputeBarAtIndexOptions): BarRect | null {
    const isGrouped = layout === 'grouped'
    if (!isGrouped && !stackedBand) {
        throw new Error(`computeBarAtIndex: stackedBand is required for layout '${layout}'`)
    }

    const bandStart = scales.band(label)
    const raw = series.data[dataIndex]
    if (bandStart == null || raw == null || !isFinite(raw)) {
        return null
    }

    const shouldRoundCap = isGrouped || isTopOfStack
    const bandWidth = scales.band.bandwidth()

    if (isGrouped) {
        const groupOffsetForKey = scales.group?.(series.key)
        const valuePixel = scales.value(raw)
        if (groupOffsetForKey == null || !isFinite(valuePixel)) {
            return null
        }
        const groupBandWidth = scales.group?.bandwidth() ?? bandWidth
        const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
        const start = bandStart + groupOffsetForKey
        return makeBarRect(isHorizontal, start, groupBandWidth, scales.value(0), valuePixel, corners, dataIndex)
    }

    const topPixel = scales.value(stackedBand!.top[dataIndex])
    const bottomPixel = scales.value(stackedBand!.bottom[dataIndex])
    if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
        return null
    }
    // For stacked/percent the bar's "positive direction" depends on which pixel is further from baseline,
    // which differs by orientation: horizontal = larger x-pixel, vertical = smaller y-pixel (axis is inverted).
    const isPositive = isHorizontal ? topPixel >= bottomPixel : topPixel <= bottomPixel
    const corners = cornersFor(isHorizontal, isPositive, shouldRoundCap)
    return makeBarRect(isHorizontal, bandStart, bandWidth, topPixel, bottomPixel, corners, dataIndex)
}
