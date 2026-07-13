import { type BarRect } from '../../../core/canvas-renderer'
import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type { ChartDrawArgs, ResolvedSeries } from '../../../core/types'
import {
    type BarLayout,
    barContainsPointOnBandAxis,
    barsAtCursor,
    cursorBeyondTrackCeiling,
    cursorOutsideBarFillExtent,
    findVisibleStackedSegment,
    isStackedLayout,
} from './bars-under-cursor'
import { stackPillRects } from './stack-pills'

export interface BarHoverItem {
    series: ResolvedSeries
    bar: BarRect
    isTrackHighlight: boolean
}

export interface ResolvedBarHover {
    items: BarHoverItem[]
    /** Per-series bar-vs-track composition string. The caller keys its fade restart on this so a
     *  bar → track move at the same `hoverIndex` still restarts the fade. */
    composition: string
    /** Rounded pills to clip the highlight to (matches the resting bars under `roundStackEnds`),
     *  or empty when not rounding stack ends. */
    hoveredBandPills: BarRect[]
}

export interface ResolveBarHoverArgs {
    barLayout: BarLayout
    isHorizontal: boolean
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    roundStackEnds: boolean
    barTrackHover: boolean
}

/** Resolve which bars (or tracks) the hovered band should highlight, plus the pill clip and a
 *  composition key. Pure — the stateful fade bookkeeping stays in the caller, which owns the
 *  alpha and then hands the result to `drawBarHoverItems`. Returns `null` when nothing is
 *  under the cursor. */
export function resolveBarHoverItems(
    { series: coloredSeries, labels: drawLabels, hoverIndex, hoverPosition }: ChartDrawArgs,
    d3Scales: BarScaleSet,
    { barLayout, isHorizontal, stackedData, topStackedKeyByAxis, roundStackEnds, barTrackHover }: ResolveBarHoverArgs
): ResolvedBarHover | null {
    const hoveredLabel = drawLabels[hoverIndex]
    const items: BarHoverItem[] = []
    let composition = ''
    // Stacked: clip the highlight to the visible slice so hover only changes shade,
    // never z-order. Grouped keeps band-axis containment for cursor-above-bar.
    const stackedHighlight = isStackedLayout(barLayout)
    if (stackedHighlight && hoverPosition) {
        const visible = findVisibleStackedSegment({
            series: coloredSeries,
            labels: drawLabels,
            hoveredLabel,
            cursor: hoverPosition,
            scales: d3Scales,
            layout: barLayout,
            isHorizontal,
            stackedData,
            topStackedKeyByAxis,
        })
        if (visible) {
            const visibleExtent = isHorizontal ? visible.bar.width : visible.bar.height
            const { nextSmallerExtent } = visible
            const baselinePx = isHorizontal ? visible.bar.x : visible.bar.y + visible.bar.height
            const clippedExtent = Math.max(0, visibleExtent - nextSmallerExtent)
            const clipped: BarRect = isHorizontal
                ? { ...visible.bar, x: baselinePx + nextSmallerExtent, width: clippedExtent }
                : { ...visible.bar, y: baselinePx - visibleExtent, height: clippedExtent }
            items.push({ series: visible.series, bar: clipped, isTrackHighlight: false })
            composition += 'b'
        }
    } else {
        for (const { series: s, bar } of barsAtCursor<ResolvedSeries>({
            series: coloredSeries,
            label: hoveredLabel,
            dataIndex: hoverIndex,
            scales: d3Scales,
            layout: barLayout,
            isHorizontal,
            stackedData,
            topStackedKeyByAxis,
        })) {
            if (hoverPosition && !barContainsPointOnBandAxis(bar, hoverPosition, isHorizontal)) {
                continue
            }
            const isTrackHighlight =
                barTrackHover &&
                barLayout === 'grouped' &&
                hoverPosition != null &&
                cursorOutsideBarFillExtent(bar, hoverPosition, isHorizontal) &&
                // Don't highlight the blank gap above a capped track (funnel compare's volume gap).
                !cursorBeyondTrackCeiling(s, bar, d3Scales, hoverPosition, isHorizontal)
            items.push({ series: s, bar, isTrackHighlight })
            composition += isTrackHighlight ? 't' : 'b'
        }
    }
    if (items.length === 0) {
        return null
    }
    // Match the resting bar's pill clip so the darker highlight rounds at the stack's outer
    // ends instead of poking square corners past them.
    const hoveredBandPills = roundStackEnds
        ? stackPillRects(
              [
                  ...barsAtCursor<ResolvedSeries>({
                      series: coloredSeries,
                      label: hoveredLabel,
                      dataIndex: hoverIndex,
                      scales: d3Scales,
                      layout: barLayout,
                      isHorizontal,
                      stackedData,
                      topStackedKeyByAxis,
                  }),
              ].map(({ bar }) => bar),
              isHorizontal
          )
        : []
    return { items, composition, hoveredBandPills }
}
