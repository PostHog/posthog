import type { BarRect, BarRoundedCorners } from './canvas-renderer'
import type { BarScaleSet, StackedBand } from './scales'
import type { Series } from './types'

/** Bars laid out for a single series across all labels, indexed by data index. */
export type SeriesBarLayout = (BarRect | null)[]

/** Pick which corners to round for a bar's cap. The cap is the side away from the
 *  value-axis baseline; for stacked layers below the topmost we don't round at all. */
export function cornersFor(isHorizontal: boolean, isPositive: boolean, shouldRoundCap: boolean): BarRoundedCorners {
    if (!shouldRoundCap) {
        return {}
    }
    if (isHorizontal) {
        return isPositive ? { topRight: true, bottomRight: true } : { topLeft: true, bottomLeft: true }
    }
    return isPositive ? { topLeft: true, topRight: true } : { bottomLeft: true, bottomRight: true }
}

/** Computes bar geometry for one series given the layout mode and band scales.
 *  Returns one entry per data index (or null when the bar is not drawable). */
export function computeSeriesBars(
    series: Series,
    labels: string[],
    scales: BarScaleSet,
    layout: 'stacked' | 'grouped' | 'percent',
    isHorizontal: boolean,
    stackedBand: StackedBand | undefined,
    isTopOfStack: boolean
): SeriesBarLayout {
    const result: SeriesBarLayout = []
    const bandWidth = scales.band.bandwidth()
    const valueAtZero = scales.value(0)

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

        // Cap is the side away from the value-axis baseline; stacked layers below the topmost don't round.
        const shouldRoundCap = layout === 'grouped' || isTopOfStack

        if (layout === 'grouped') {
            const groupOffset = scales.group?.(series.key)
            if (groupOffset == null) {
                result.push(null)
                continue
            }
            const groupBandWidth = scales.group?.bandwidth() ?? bandWidth
            const valuePixel = scales.value(raw)
            if (!isFinite(valuePixel)) {
                result.push(null)
                continue
            }

            const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
            if (isHorizontal) {
                const x = Math.min(valueAtZero, valuePixel)
                const width = Math.abs(valuePixel - valueAtZero)
                result.push({
                    x,
                    y: bandStart + groupOffset,
                    width,
                    height: groupBandWidth,
                    corners,
                    dataIndex: i,
                })
            } else {
                const y = Math.min(valueAtZero, valuePixel)
                const height = Math.abs(valuePixel - valueAtZero)
                result.push({
                    x: bandStart + groupOffset,
                    y,
                    width: groupBandWidth,
                    height,
                    corners,
                    dataIndex: i,
                })
            }
            continue
        }

        // Stacked / percent: use the band's stacked top/bottom values.
        const top = stackedBand?.top[i] ?? raw
        const bottom = stackedBand?.bottom[i] ?? 0
        const topPixel = scales.value(top)
        const bottomPixel = scales.value(bottom)
        if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
            result.push(null)
            continue
        }

        if (isHorizontal) {
            const x = Math.min(topPixel, bottomPixel)
            const width = Math.abs(topPixel - bottomPixel)
            result.push({
                x,
                y: bandStart,
                width,
                height: bandWidth,
                corners: shouldRoundCap ? { topRight: true, bottomRight: true } : {},
                dataIndex: i,
            })
        } else {
            const y = Math.min(topPixel, bottomPixel)
            const height = Math.abs(topPixel - bottomPixel)
            result.push({
                x: bandStart,
                y,
                width: bandWidth,
                height,
                corners: shouldRoundCap ? { topLeft: true, topRight: true } : {},
                dataIndex: i,
            })
        }
    }
    return result
}
