import type { BarRect, BarRoundedCorners } from './canvas-renderer'
import { type BarScaleSet, groupedBandSlot, type StackedBand } from './scales'
import type { ResolvedSeries, Series } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

/** Brand for the BarChart `ChartScales._private` slot — populated by BarChart and
 *  narrowed by its draw callbacks. */
export interface BarChartPrivate {
    __barChart: BarScaleSet
}

export type SeriesBarLayout = (BarRect | null)[]

// Sub-pixel overlap between adjacent stacked segments, to hide anti-aliased seams at shared edges.
const STACK_SEGMENT_OVERLAP_PX = 0.5

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

// A segment thinner than this can't visibly carry a rounded cap; skipping it stops an invisible
// sliver (e.g. a zero-valued breakdown at the top of the stack order) from stealing the cap.
const MIN_CAP_SEGMENT_PX = 0.5

/** Re-resolve stacked cap rounding per band, geometrically, from the laid-out rects: within each
 *  `dataIndex`, only the segment reaching furthest away from the baseline in each direction keeps
 *  a rounded cap — everything else's cap is squared. Decided after layout so breakdown stacks
 *  (whose top layer varies band to band) and diverging stacks (negative bottoms) round the actual
 *  outer segment, not the last series in stack order. Mutates `corners` in place; baseline
 *  corners are untouched. */
export function roundOuterStackCaps(bars: BarRect[], isHorizontal: boolean, baselinePx: number): void {
    const outerPositive = new Map<number, BarRect>()
    const outerNegative = new Map<number, BarRect>()
    for (const bar of bars) {
        const size = isHorizontal ? bar.width : bar.height
        if (size < MIN_CAP_SEGMENT_PX) {
            continue
        }
        // The cap edge, signed so "further from the baseline" compares uniformly per direction.
        // Vertical: smaller y is further up; horizontal: larger x+width is further right.
        if (isHorizontal) {
            if (bar.x + bar.width > baselinePx + MIN_CAP_SEGMENT_PX) {
                const prev = outerPositive.get(bar.dataIndex)
                if (!prev || bar.x + bar.width >= prev.x + prev.width) {
                    outerPositive.set(bar.dataIndex, bar)
                }
            }
            if (bar.x < baselinePx - MIN_CAP_SEGMENT_PX) {
                const prev = outerNegative.get(bar.dataIndex)
                if (!prev || bar.x <= prev.x) {
                    outerNegative.set(bar.dataIndex, bar)
                }
            }
        } else {
            if (bar.y < baselinePx - MIN_CAP_SEGMENT_PX) {
                const prev = outerPositive.get(bar.dataIndex)
                if (!prev || bar.y <= prev.y) {
                    outerPositive.set(bar.dataIndex, bar)
                }
            }
            if (bar.y + bar.height > baselinePx + MIN_CAP_SEGMENT_PX) {
                const prev = outerNegative.get(bar.dataIndex)
                if (!prev || bar.y + bar.height >= prev.y + prev.height) {
                    outerNegative.set(bar.dataIndex, bar)
                }
            }
        }
    }
    for (const bar of bars) {
        const isOuterPositive = outerPositive.get(bar.dataIndex) === bar
        const isOuterNegative = outerNegative.get(bar.dataIndex) === bar
        // Rewrite only the bar's own cap side (away from the baseline), so baseline-side rounding
        // a caller may have applied is preserved.
        const positive = isHorizontal ? bar.x + bar.width > baselinePx : bar.y < baselinePx
        const cap = isOuterPositive || isOuterNegative || undefined
        if (isHorizontal) {
            if (positive) {
                bar.corners.topRight = bar.corners.bottomRight = cap
            } else {
                bar.corners.topLeft = bar.corners.bottomLeft = cap
            }
        } else if (positive) {
            bar.corners.topLeft = bar.corners.topRight = cap
        } else {
            bar.corners.bottomLeft = bar.corners.bottomRight = cap
        }
    }
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

/** One drawn series and its computed rects — the unit both BarChart and ComboChart iterate. */
export interface BarLayer {
    series: ResolvedSeries
    bars: BarRect[]
}

export interface BuildBarLayersOptions {
    series: readonly ResolvedSeries[]
    labels: string[]
    scales: BarScaleSet
    layout: 'stacked' | 'grouped' | 'percent'
    isHorizontal: boolean
    stackedData?: Map<string, StackedBand>
    topStackedKeyByAxis: Map<string, string>
}

/** Compute the bar rects for every visible series — the per-series `computeSeriesBars` loop shared by
 *  `drawBarChartStatic` and ComboChart so the band/axis/stack wiring lives in one place. Excluded
 *  series are dropped; nulls (overlay/CI-band series with no stacked entry) are filtered out. */
export function buildBarLayers({
    series,
    labels,
    scales,
    layout,
    isHorizontal,
    stackedData,
    topStackedKeyByAxis,
}: BuildBarLayersOptions): BarLayer[] {
    const layers: BarLayer[] = []
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const bars = computeSeriesBars({
            series: s,
            labels,
            scales,
            layout,
            isHorizontal,
            stackedBand: stackedData?.get(s.key),
            isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
        }).filter((b): b is BarRect => b !== null)
        layers.push({ series: s, bars })
    }
    return layers
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

    // Grouped multi-axis: each series scales against its own value axis. Falls back to the
    // shared `value` scale when only one axis is present (`yAxes` unset).
    const valueScale = scales.yAxes?.[series.yAxisId ?? DEFAULT_Y_AXIS_ID]?.scale ?? scales.value

    if (isGrouped) {
        const slot = groupedBandSlot(scales, label, series.key)
        const valuePixel = valueScale(raw)
        if (!slot || !isFinite(valuePixel)) {
            return null
        }
        const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
        // A fixed `valueDomain` (e.g. [50, 100]) makes `valueScale(0)` extrapolate outside the
        // plot, so the bar would bleed through the axis. Clamp the baseline to the scale's range.
        const [r0, r1] = valueScale.range()
        const baseline = Math.min(Math.max(valueScale(0), Math.min(r0, r1)), Math.max(r0, r1))
        return makeBarRect(isHorizontal, slot.x, slot.width, baseline, valuePixel, corners, dataIndex)
    }

    // Resolve against the series' own axis (mirrors the grouped branch above), so a stacked bar on
    // a non-default `yAxisId` — only ComboChart combines stacking with per-series axes — is hit-tested
    // and drawn against the same scale. For single-axis charts `valueScale` is `scales.value`.
    const topPixel = valueScale(stackedBand!.top[dataIndex])
    const bottomPixel = valueScale(stackedBand!.bottom[dataIndex])
    if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
        return null
    }
    // For stacked/percent the bar's "positive direction" depends on which pixel is further from baseline,
    // which differs by orientation: horizontal = larger x-pixel, vertical = smaller y-pixel (axis is inverted).
    const isPositive = isHorizontal ? topPixel >= bottomPixel : topPixel <= bottomPixel
    const corners = cornersFor(isHorizontal, isPositive, shouldRoundCap, shouldRoundBaseline)
    // Extend an interior segment a sub-pixel toward the baseline so it overlaps its lower neighbour,
    // hiding the faint anti-aliased seam where two adjacent fills meet on a fractional device pixel.
    // The bottom-of-stack segment sits on the value-axis baseline, so it's left exact — extending it
    // would only overpaint the axis. The cap (away-from-baseline) side is always exact so cap
    // rounding and the stack's outer edge stay put.
    const sitsOnBaseline = Math.abs(bottomPixel - valueScale(0)) < 0.001
    const overlappedBottom = sitsOnBaseline
        ? bottomPixel
        : bottomPixel + STACK_SEGMENT_OVERLAP_PX * Math.sign(bottomPixel - topPixel)
    return makeBarRect(isHorizontal, bandStart, bandWidth, topPixel, overlappedBottom, corners, dataIndex)
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

/** Pixel center of a band along the band axis — the anchor for band-level tooltips and grid ticks. */
export function bandCenter(scales: BarScaleSet, label: string): number | undefined {
    const start = scales.band(label)
    return start == null ? undefined : start + scales.band.bandwidth() / 2
}

/** Center of a specific series's bar within a band. Used by overlays (e.g. annotations)
 *  to anchor on the current-period bar in compare-against-previous grouped layouts.
 *  Returns undefined when the layout isn't grouped or the series isn't in the group scale. */
export function groupedBarCenter(scales: BarScaleSet, label: string, seriesKey: string): number | undefined {
    const slot = groupedBandSlot(scales, label, seriesKey)
    return slot && slot.x + slot.width / 2
}
