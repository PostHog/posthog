import type { BarRect, BarRoundedCorners } from './canvas-renderer'
import type { BarScaleSet, StackedBand } from './scales'
import type { Series } from './types'

export type SeriesBarLayout = (BarRect | null)[]

/** Cap is the side away from the value-axis baseline; for stacked layers below the topmost
 *  the caller should pass `shouldRoundCap: false`. */
export function cornersFor(isHorizontal: boolean, isPositive: boolean, shouldRoundCap: boolean): BarRoundedCorners {
    if (!shouldRoundCap) {
        return {}
    }
    if (isHorizontal) {
        return isPositive ? { topRight: true, bottomRight: true } : { topLeft: true, bottomLeft: true }
    }
    return isPositive ? { topLeft: true, topRight: true } : { bottomLeft: true, bottomRight: true }
}

export interface ComputeSeriesBarsOptions {
    series: Series
    labels: string[]
    scales: BarScaleSet
    layout: 'stacked' | 'grouped' | 'percent'
    isHorizontal: boolean
    stackedBand: StackedBand | undefined
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
    const result: SeriesBarLayout = []
    const bandWidth = scales.band.bandwidth()
    const valueAtZero = scales.value(0)
    const isGrouped = layout === 'grouped'
    const shouldRoundCap = isGrouped || isTopOfStack
    const groupOffsetForKey = isGrouped ? scales.group?.(series.key) : undefined
    const groupBandWidth = isGrouped ? (scales.group?.bandwidth() ?? bandWidth) : bandWidth

    for (let i = 0; i < labels.length; i++) {
        const bandStart = scales.band(labels[i])
        if (bandStart == null) {
            result.push(null)
            continue
        }

        const raw = series.data[i]
        if (raw == null || !isFinite(raw)) {
            result.push(null)
            continue
        }

        if (isGrouped) {
            if (groupOffsetForKey == null) {
                result.push(null)
                continue
            }
            const valuePixel = scales.value(raw)
            if (!isFinite(valuePixel)) {
                result.push(null)
                continue
            }

            const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
            if (isHorizontal) {
                result.push({
                    x: Math.min(valueAtZero, valuePixel),
                    y: bandStart + groupOffsetForKey,
                    width: Math.abs(valuePixel - valueAtZero),
                    height: groupBandWidth,
                    corners,
                    dataIndex: i,
                })
            } else {
                result.push({
                    x: bandStart + groupOffsetForKey,
                    y: Math.min(valueAtZero, valuePixel),
                    width: groupBandWidth,
                    height: Math.abs(valuePixel - valueAtZero),
                    corners,
                    dataIndex: i,
                })
            }
            continue
        }

        // Stacked / percent: stack data is non-negative (computeStackData clamps via Math.max(0, …)),
        // so cornersFor's `isPositive=true` is correct here.
        const top = stackedBand?.top[i] ?? raw
        const bottom = stackedBand?.bottom[i] ?? 0
        const topPixel = scales.value(top)
        const bottomPixel = scales.value(bottom)
        if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
            result.push(null)
            continue
        }

        const corners = cornersFor(isHorizontal, true, shouldRoundCap)
        if (isHorizontal) {
            result.push({
                x: Math.min(topPixel, bottomPixel),
                y: bandStart,
                width: Math.abs(topPixel - bottomPixel),
                height: bandWidth,
                corners,
                dataIndex: i,
            })
        } else {
            result.push({
                x: bandStart,
                y: Math.min(topPixel, bottomPixel),
                width: bandWidth,
                height: Math.abs(topPixel - bottomPixel),
                corners,
                dataIndex: i,
            })
        }
    }
    return result
}
