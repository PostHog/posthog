import { color as d3Color } from 'd3-color'

import { bandCenter, type BarChartPrivate, computeBarTrackRect, computeSeriesBars } from '../../../core/bar-layout'
import {
    BAR_TRACK_HOVER_ALPHA,
    type BarRect,
    type BarRoundedCorners,
    type BarShadow,
    clipToRoundedRects,
    drawBarHighlight,
    drawBars,
    drawBarTracks,
    drawGrid,
    type DrawContext,
} from '../../../core/canvas-renderer'
import { barColorAt } from '../../../core/color-utils'
import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type {
    BarChartConfig,
    BarFillStyle,
    BarsConfig,
    ChartDimensions,
    ChartDrawArgs,
    ResolvedSeries,
} from '../../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../../core/types'
import { computeVisibleXLabels } from '../../../overlays/AxisLabels'
import { resolveBarShadow } from './bar-config'
import {
    type BarLayout,
    barContainsPointOnBandAxis,
    cursorOutsideBarFillExtent,
    findVisibleStackedSegment,
    isStackedLayout,
    iterBarsAtCursor,
} from './bars-under-cursor'

const ALL_CORNERS: BarRoundedCorners = { topLeft: true, topRight: true, bottomLeft: true, bottomRight: true }

/** One fully-rounded rect per band, spanning the union of that band's stacked segments — the
 *  pill the bar layer is clipped to for `roundStackEnds`. Bars in the same band share a band-axis
 *  slot (same `dataIndex`), so we group by it and extend along the value axis. */
function stackPillRects(bars: BarRect[], isHorizontal: boolean): BarRect[] {
    const byBand = new Map<number, BarRect>()
    for (const bar of bars) {
        if (bar.width <= 0 || bar.height <= 0) {
            continue
        }
        const existing = byBand.get(bar.dataIndex)
        if (!existing) {
            byBand.set(bar.dataIndex, { ...bar, corners: ALL_CORNERS })
            continue
        }
        if (isHorizontal) {
            const left = Math.min(existing.x, bar.x)
            const right = Math.max(existing.x + existing.width, bar.x + bar.width)
            existing.x = left
            existing.width = right - left
        } else {
            const top = Math.min(existing.y, bar.y)
            const bottom = Math.max(existing.y + existing.height, bar.y + bar.height)
            existing.y = top
            existing.height = bottom - top
        }
    }
    return [...byBand.values()]
}

/** Category-axis grid ticks aligned to the visible labels rather than every band: all band
 *  centers for horizontal charts, the de-duplicated visible x-labels for vertical ones so a
 *  dense axis stays legible. */
function computeGridTicks(
    d3Scales: BarScaleSet,
    drawLabels: string[],
    isHorizontal: boolean,
    xTickFormatter: BarChartConfig['xTickFormatter']
): number[] {
    if (isHorizontal) {
        const ticks: number[] = []
        for (const label of drawLabels) {
            const coord = bandCenter(d3Scales, label)
            if (coord != null && isFinite(coord)) {
                ticks.push(coord)
            }
        }
        return ticks
    }
    return computeVisibleXLabels(drawLabels, (label) => bandCenter(d3Scales, label), xTickFormatter).map(
        (entry) => entry.x
    )
}

/** Run `draw` with the bar drop-shadow active, clipped to the plot area so a 100% bar's upward
 *  shadow doesn't bleed past the chart edge. No-op wrapper (just calls `draw`) when no shadow. */
function withBarShadow(
    ctx: CanvasRenderingContext2D,
    dimensions: ChartDimensions,
    shadow: BarShadow | undefined,
    draw: () => void
): void {
    if (!shadow) {
        draw()
        return
    }
    ctx.save()
    ctx.beginPath()
    ctx.rect(dimensions.plotLeft, dimensions.plotTop, dimensions.plotWidth, dimensions.plotHeight)
    ctx.clip()
    ctx.shadowColor = shadow.color
    ctx.shadowBlur = shadow.blur
    ctx.shadowOffsetX = shadow.offsetX ?? 0
    ctx.shadowOffsetY = shadow.offsetY ?? 0
    draw()
    ctx.restore()
}

export interface DrawBarChartStaticArgs {
    barLayout: BarLayout
    isHorizontal: boolean
    showGrid: boolean
    xTickFormatter: BarChartConfig['xTickFormatter']
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    roundStackEnds: boolean
    barCornerRadius: number
    barTrack: boolean
    barShadow: BarsConfig['shadow']
    barFillStyle: BarFillStyle
}

/** The full static pass: grid, bars, optional tracks, optional drop shadow and rounded stack
 *  pills. Reads the d3 scales from the committed `ChartScales._private` slot so it works off a
 *  self-contained per-render object. No React, no component state. */
export function drawBarChartStatic(
    { ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs,
    {
        barLayout,
        isHorizontal,
        showGrid,
        xTickFormatter,
        stackedData,
        topStackedKeyByAxis,
        roundStackEnds,
        barCornerRadius,
        barTrack,
        barShadow,
        barFillStyle,
    }: DrawBarChartStaticArgs
): void {
    const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
    if (!d3Scales) {
        return
    }

    const baseDrawCtx: DrawContext = {
        ctx,
        dimensions,
        xScale: (label: string) => bandCenter(d3Scales, label),
        yScale: d3Scales.value,
        labels: drawLabels,
    }

    if (showGrid) {
        drawGrid(baseDrawCtx, {
            gridColor: theme.gridColor,
            orientation: isHorizontal ? 'horizontal' : 'vertical',
            categoryTicks: computeGridTicks(d3Scales, drawLabels, isHorizontal, xTickFormatter),
        })
    }

    const seriesBars = coloredSeries
        .filter((s) => !s.visibility?.excluded)
        .map((s) => {
            const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
            const bars = computeSeriesBars({
                series: s,
                labels: drawLabels,
                scales: d3Scales,
                layout: barLayout,
                isHorizontal,
                stackedBand: stackedData?.get(s.key),
                isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
            }).filter((b): b is BarRect => b !== null)
            return { series: s, bars }
        })

    // `roundStackEnds`: round both outer ends of the whole stack into a pill by clipping
    // the bar layer to a rounded rect spanning each band's full extent, then drawing the
    // segments square. The clip rounds the outer corners at the full radius even when the
    // edge segment is a thin sliver (e.g. the last breakdown of a near-100% step), which
    // per-segment rounding can't — it would clamp the radius to the sliver's half-width.
    const stackPills = roundStackEnds
        ? stackPillRects(
              seriesBars.flatMap((sb) => sb.bars),
              isHorizontal
          )
        : []

    // Tracks are a separate pass so a later series' full-height track can't paint
    // over an earlier series' bar. Track is "share of a whole" semantics — only
    // meaningful for grouped layouts; in stacked/percent every layer would paint
    // a full-height track over the same band with the wrong corners.
    if (barTrack && barLayout === 'grouped') {
        const [axisStart = 0, axisEnd = 0] = d3Scales.value.range()
        for (const { series: s, bars } of seriesBars) {
            const tracks = bars.map((b) => computeBarTrackRect(b, axisStart, axisEnd, isHorizontal))
            drawBarTracks(baseDrawCtx, s, tracks, barCornerRadius)
        }
    }

    withBarShadow(ctx, dimensions, resolveBarShadow(barShadow), () => {
        if (stackPills.length > 0) {
            ctx.save()
            clipToRoundedRects(ctx, stackPills, barCornerRadius)
        }
        for (const { series: s, bars } of seriesBars) {
            drawBars(baseDrawCtx, s, bars, stackPills.length > 0 ? 0 : barCornerRadius, barFillStyle)
        }
        if (stackPills.length > 0) {
            ctx.restore()
        }
    })
}

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
    barTrack: boolean
}

/** Resolve which bars (or tracks) the hovered band should highlight, plus the pill clip and a
 *  composition key. Pure — the stateful fade bookkeeping stays in the caller, which owns the
 *  alpha and then hands the result to {@link drawBarHoverItems}. Returns `null` when nothing is
 *  under the cursor. */
export function resolveBarHoverItems(
    { series: coloredSeries, labels: drawLabels, hoverIndex, hoverPosition }: ChartDrawArgs,
    d3Scales: BarScaleSet,
    { barLayout, isHorizontal, stackedData, topStackedKeyByAxis, roundStackEnds, barTrack }: ResolveBarHoverArgs
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
        for (const { series: s, bar } of iterBarsAtCursor<ResolvedSeries>({
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
                barTrack === true &&
                barLayout === 'grouped' &&
                hoverPosition != null &&
                cursorOutsideBarFillExtent(bar, hoverPosition, isHorizontal)
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
                  ...iterBarsAtCursor<ResolvedSeries>({
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

export interface DrawBarHoverArgs {
    alpha: number
    barCornerRadius: number
    barTrack: boolean
    isHorizontal: boolean
}

/** Paint the resolved hover highlight. Track highlights draw a translucent full-extent rect; bar
 *  highlights draw a darker shade of the bar color. Clips to the pills from
 *  {@link resolveBarHoverItems} when rounding stack ends. */
export function drawBarHoverItems(
    ctx: CanvasRenderingContext2D,
    d3Scales: BarScaleSet,
    { items, hoveredBandPills }: ResolvedBarHover,
    { alpha, barCornerRadius, barTrack, isHorizontal }: DrawBarHoverArgs
): void {
    const [trackAxisStart = 0, trackAxisEnd = 0] = barTrack ? d3Scales.value.range() : []
    const highlightRadius = hoveredBandPills.length > 0 ? 0 : barCornerRadius
    ctx.save()
    ctx.globalAlpha = alpha
    if (hoveredBandPills.length > 0) {
        clipToRoundedRects(ctx, hoveredBandPills, barCornerRadius)
    }
    for (const { series: s, bar, isTrackHighlight } of items) {
        if (isTrackHighlight) {
            const parsed = d3Color(barColorAt(s, bar.dataIndex))
            // Always translucent — the bar color direct would paint an opaque full-height
            // block if d3 can't parse the color.
            let trackColor: string
            if (parsed) {
                parsed.opacity = BAR_TRACK_HOVER_ALPHA
                trackColor = parsed.toString()
            } else {
                trackColor = `rgba(0,0,0,${BAR_TRACK_HOVER_ALPHA})`
            }
            drawBarHighlight(
                ctx,
                computeBarTrackRect(bar, trackAxisStart, trackAxisEnd, isHorizontal),
                trackColor,
                highlightRadius
            )
        } else {
            const barColor = barColorAt(s, bar.dataIndex)
            const highlightColor = d3Color(barColor)?.darker(0.6).toString() ?? barColor
            drawBarHighlight(ctx, bar, highlightColor, highlightRadius)
        }
    }
    ctx.restore()
}
