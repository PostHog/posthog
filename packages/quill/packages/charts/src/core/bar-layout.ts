import type { BarRect, BarRoundedCorners } from './canvas-renderer'
import { type BarScaleSet, groupedBandSlot, type StackedBand } from './scales'
import type { Series } from './types'

/** Brand for the BarChart `ChartScales._private` slot — populated by BarChart and
 *  narrowed by its draw callbacks. */
export interface BarChartPrivate {
    __barChart: BarScaleSet
}

export type SeriesBarLayout = (BarRect | null)[]

/** Cap is the side away from the value-axis baseline; pass `shouldRoundCap: false` for stacked
 *  layers below the topmost. `shouldRoundBaseline` rounds the side *towards* the baseline — used
 *  for the bottom-of-stack layer so a funnel-style bar reads as one rounded pill on both ends. */
export function cornersFor(
    isHorizontal: boolean,
    isPositive: boolean,
    shouldRoundCap: boolean,
    shouldRoundBaseline: boolean = false
): BarRoundedCorners {
    const corners: BarRoundedCorners = {}
    if (shouldRoundCap) {
        if (isHorizontal) {
            if (isPositive) {
                corners.topRight = corners.bottomRight = true
            } else {
                corners.topLeft = corners.bottomLeft = true
            }
        } else if (isPositive) {
            corners.topLeft = corners.topRight = true
        } else {
            corners.bottomLeft = corners.bottomRight = true
        }
    }
    if (shouldRoundBaseline) {
        if (isHorizontal) {
            if (isPositive) {
                corners.topLeft = corners.bottomLeft = true
            } else {
                corners.topRight = corners.bottomRight = true
            }
        } else if (isPositive) {
            corners.bottomLeft = corners.bottomRight = true
        } else {
            corners.topLeft = corners.topRight = true
        }
    }
    return corners
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
    /** Per-index override for cap rounding — funnels round whichever segment is the topmost
     *  *non-zero* one at each band, which varies by band (e.g. a 100% first step has no
     *  filler). When omitted, falls back to the per-series `isTopOfStack`. */
    capRoundedAtIndex?: (dataIndex: number) => boolean
    /** Per-index override for baseline rounding — rounds the side towards the value-axis
     *  baseline for the bottom-of-stack segment. When omitted, the baseline is never rounded. */
    baseRoundedAtIndex?: (dataIndex: number) => boolean
}

export function computeSeriesBars({
    series,
    labels,
    scales,
    layout,
    isHorizontal,
    stackedBand,
    isTopOfStack,
    capRoundedAtIndex,
    baseRoundedAtIndex,
}: ComputeSeriesBarsOptions): SeriesBarLayout {
    const result: SeriesBarLayout = new Array(labels.length)
    for (let i = 0; i < labels.length; i++) {
        result[i] = computeBarAtIndex({
            series,
            label: labels[i],
            dataIndex: i,
            scales,
            isHorizontal,
            layout,
            stackedBand,
            isTopOfStack,
            capRounded: capRoundedAtIndex?.(i),
            baseRounded: baseRoundedAtIndex?.(i),
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
    /** Resolved cap-rounding for this bar. Overrides the `isGrouped || isTopOfStack` default. */
    capRounded?: boolean
    /** Resolved baseline-rounding for this bar. Defaults to `false`. */
    baseRounded?: boolean
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
    capRounded,
    baseRounded,
}: ComputeBarAtIndexOptions): BarRect | null {
    const isGrouped = layout === 'grouped'
    if (!isGrouped && !stackedBand) {
        // Overlay / CI-band series are intentionally excluded from buildStackData, so they
        // have no stackedBand entry. Treat them as non-renderable for the bar layer rather
        // than throwing — hover/tooltip paths iterate every series in the chart context.
        return null
    }

    const bandStart = scales.band(label)
    const raw = series.data[dataIndex]
    if (bandStart == null || raw == null || !isFinite(raw)) {
        return null
    }

    const shouldRoundCap = capRounded ?? (isGrouped || isTopOfStack)
    const shouldRoundBaseline = isGrouped ? false : (baseRounded ?? false)
    const bandWidth = scales.band.bandwidth()

    if (isGrouped) {
        const slot = groupedBandSlot(scales, label, series.key)
        const valuePixel = scales.value(raw)
        if (!slot || !isFinite(valuePixel)) {
            return null
        }
        const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
        return makeBarRect(isHorizontal, slot.x, slot.width, scales.value(0), valuePixel, corners, dataIndex)
    }

    const topPixel = scales.value(stackedBand!.top[dataIndex])
    const bottomPixel = scales.value(stackedBand!.bottom[dataIndex])
    if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
        return null
    }
    // For stacked/percent the bar's "positive direction" depends on which pixel is further from baseline,
    // which differs by orientation: horizontal = larger x-pixel, vertical = smaller y-pixel (axis is inverted).
    const isPositive = isHorizontal ? topPixel >= bottomPixel : topPixel <= bottomPixel
    const corners = cornersFor(isHorizontal, isPositive, shouldRoundCap, shouldRoundBaseline)
    return makeBarRect(isHorizontal, bandStart, bandWidth, topPixel, bottomPixel, corners, dataIndex)
}

/** The track rect behind a bar — the bar's band slot stretched across the whole value
 *  axis. `axisRangeA`/`axisRangeB` are the two endpoints of the value scale's pixel range
 *  (in either order — for a vertical Y scale d3 returns `[bottomPx, topPx]`). Used by
 *  funnel-style charts to draw and hit-test the faint "remainder to 100%" region. */
export function computeBarTrackRect(
    bar: BarRect,
    axisRangeA: number,
    axisRangeB: number,
    isHorizontal: boolean
): BarRect {
    const valueMin = Math.min(axisRangeA, axisRangeB)
    const valueSize = Math.abs(axisRangeB - axisRangeA)
    return isHorizontal
        ? {
              x: valueMin,
              y: bar.y,
              width: valueSize,
              height: bar.height,
              corners: bar.corners,
              dataIndex: bar.dataIndex,
          }
        : { x: bar.x, y: valueMin, width: bar.width, height: valueSize, corners: bar.corners, dataIndex: bar.dataIndex }
}
