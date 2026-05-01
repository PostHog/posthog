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
    const isGrouped = layout === 'grouped'
    if (!isGrouped && !stackedBand) {
        throw new Error(`computeSeriesBars: stackedBand is required for layout '${layout}'`)
    }

    const result: SeriesBarLayout = []
    const bandWidth = scales.band.bandwidth()
    const valueAtZero = scales.value(0)
    const shouldRoundCap = isGrouped || isTopOfStack
    const groupOffsetForKey = isGrouped ? scales.group?.(series.key) : undefined
    const groupBandWidth = isGrouped ? (scales.group?.bandwidth() ?? bandWidth) : bandWidth
    // For stacked/percent the bar's "positive direction" depends on which pixel is further from baseline,
    // which differs by orientation: horizontal = larger x-pixel, vertical = smaller y-pixel (axis is inverted).
    const isPositiveByPixels = (topPx: number, bottomPx: number): boolean =>
        isHorizontal ? topPx >= bottomPx : topPx <= bottomPx

    for (let i = 0; i < labels.length; i++) {
        const bandStart = scales.band(labels[i])
        const raw = series.data[i]
        if (bandStart == null || raw == null || !isFinite(raw)) {
            result.push(null)
            continue
        }

        if (isGrouped) {
            const valuePixel = scales.value(raw)
            if (groupOffsetForKey == null || !isFinite(valuePixel)) {
                result.push(null)
                continue
            }
            const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
            const start = bandStart + groupOffsetForKey
            result.push(makeBarRect(isHorizontal, start, groupBandWidth, valueAtZero, valuePixel, corners, i))
            continue
        }

        const topPixel = scales.value(stackedBand!.top[i])
        const bottomPixel = scales.value(stackedBand!.bottom[i])
        if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
            result.push(null)
            continue
        }
        const corners = cornersFor(isHorizontal, isPositiveByPixels(topPixel, bottomPixel), shouldRoundCap)
        result.push(makeBarRect(isHorizontal, bandStart, bandWidth, topPixel, bottomPixel, corners, i))
    }
    return result
}
