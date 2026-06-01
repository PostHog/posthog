import * as d3 from 'd3'

import { type BarChartPrivate, bandCenter, computeBarTrackRect, computeSeriesBars } from '../../../core/bar-layout'
import {
    BAR_TRACK_HOVER_ALPHA,
    type BarRect,
    drawBarHighlight,
    drawBars,
    drawBarTracks,
    drawGrid,
    type DrawContext,
} from '../../../core/canvas-renderer'
import type { StackedBand } from '../../../core/scales'
import type { BarsConfig, ChartDrawArgs, ResolvedSeries } from '../../../core/types'
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

/** Bar-specific draw inputs threaded from `BarChart` config into the canvas passes. */
export interface BarChartDrawConfig {
    barLayout: BarLayout
    isHorizontal: boolean
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    barCornerRadius: number
    barTrack: boolean
    showGrid: boolean
    xTickFormatter?: (value: string, index: number) => string | null
    barShadow: BarsConfig['shadow']
}

/** Static (non-hover) bar layer: optional grid, per-series bars, tracks, and drop shadow.
 *  Pure canvas work — all React state arrives via `args` and `config`. */
export function drawBarChartStatic(args: ChartDrawArgs, config: BarChartDrawConfig): void {
    const { ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme } = args
    const { showGrid, isHorizontal, xTickFormatter, barLayout, stackedData, topStackedKeyByAxis } = config
    const { barTrack, barCornerRadius, barShadow } = config

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
        // Align cross-axis grid with visible category labels, not every band.
        let categoryTicks: number[] = []
        if (isHorizontal) {
            for (const label of drawLabels) {
                const coord = bandCenter(d3Scales, label)
                if (coord != null && isFinite(coord)) {
                    categoryTicks.push(coord)
                }
            }
        } else {
            categoryTicks = computeVisibleXLabels(
                drawLabels,
                (label) => bandCenter(d3Scales, label),
                xTickFormatter
            ).map((entry) => entry.x)
        }
        drawGrid(baseDrawCtx, {
            gridColor: theme.gridColor,
            orientation: isHorizontal ? 'horizontal' : 'vertical',
            categoryTicks,
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

    const resolvedShadow = resolveBarShadow(barShadow)
    // Clip to plot area so a 100% bar's upward shadow doesn't bleed past the chart edge.
    if (resolvedShadow) {
        ctx.save()
        ctx.beginPath()
        ctx.rect(dimensions.plotLeft, dimensions.plotTop, dimensions.plotWidth, dimensions.plotHeight)
        ctx.clip()
        ctx.shadowColor = resolvedShadow.color
        ctx.shadowBlur = resolvedShadow.blur
        ctx.shadowOffsetX = resolvedShadow.offsetX ?? 0
        ctx.shadowOffsetY = resolvedShadow.offsetY ?? 0
    }
    for (const { series: s, bars } of seriesBars) {
        drawBars(baseDrawCtx, s, bars, barCornerRadius)
    }
    if (resolvedShadow) {
        ctx.restore()
    }
}

export interface BarHoverItem {
    series: ResolvedSeries
    bar: BarRect
    isTrackHighlight: boolean
}

export interface BarHoverResolution {
    items: BarHoverItem[]
    /** Per-series bar-vs-track marker (`b`/`t`) — distinguishes a bar → track move at the same
     *  hoverIndex so the caller can restart the fade. */
    composition: string
    /** Value-axis pixel range used to size track highlights; `[0, 0]` when tracks are off. */
    trackAxisRange: [number, number]
}

/** Resolves which bars/tracks to highlight under the cursor. Pure — returns `null` when there's
 *  nothing to highlight (no scales, no hover, or the cursor missed every bar). Drawing is left to
 *  {@link drawBarHoverItems} so the caller can own the hover-fade alpha between resolve and draw. */
export function resolveBarHoverItems(args: ChartDrawArgs, config: BarChartDrawConfig): BarHoverResolution | null {
    const { scales, series: coloredSeries, labels: drawLabels, hoverIndex, hoverPosition } = args
    const { barLayout, isHorizontal, stackedData, topStackedKeyByAxis, barTrack } = config

    const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
    if (!d3Scales || hoverIndex < 0) {
        return null
    }
    const hoveredLabel = drawLabels[hoverIndex]
    const [trackAxisStart = 0, trackAxisEnd = 0] = barTrack ? d3Scales.value.range() : []
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
    return { items, composition, trackAxisRange: [trackAxisStart, trackAxisEnd] }
}

/** Paints the highlights resolved by {@link resolveBarHoverItems}. The caller sets
 *  `ctx.globalAlpha` (the hover-fade) and wraps in save/restore. */
export function drawBarHoverItems(
    ctx: CanvasRenderingContext2D,
    items: BarHoverItem[],
    {
        barCornerRadius,
        isHorizontal,
        trackAxisRange,
    }: { barCornerRadius: number; isHorizontal: boolean; trackAxisRange: [number, number] }
): void {
    const [trackAxisStart, trackAxisEnd] = trackAxisRange
    for (const { series: s, bar, isTrackHighlight } of items) {
        if (isTrackHighlight) {
            const parsed = d3.color(s.color)
            // Always translucent — `s.color` direct would paint an opaque full-height
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
                barCornerRadius
            )
        } else {
            const highlightColor = d3.color(s.color)?.darker(0.6).toString() ?? s.color
            drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
        }
    }
}
