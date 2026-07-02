import { color as d3Color } from 'd3-color'

import {
    bandCenter,
    type BarChartPrivate,
    buildBarLayers,
    computeBarTrackRect,
    roundOuterStackCaps,
} from '../../../core/bar-layout'
import {
    BAR_HIGHLIGHT_DARKEN,
    BAR_TRACK_HOVER_ALPHA,
    type BarShadow,
    clipToRoundedRects,
    drawAxes,
    drawBarHighlight,
    drawBars,
    drawBarTracks,
    drawGrid,
    resolveAxisLineColor,
    type DrawContext,
} from '../../../core/canvas-renderer'
import { barColorAt } from '../../../core/color-utils'
import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type { BarChartConfig, BarFillStyle, BarsConfig, ChartDimensions, ChartDrawArgs } from '../../../core/types'
import { computeVisibleXLabels } from '../../../overlays/AxisLabels'
import { resolveBarShadow } from './bar-config'
import { type BarLayout } from './bars-under-cursor'
import type { ResolvedBarHover } from './resolve-bar-hover'
import { stackPillRects } from './stack-pills'

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
    showAxisLines: boolean
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
        showAxisLines,
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

    // Grid sits behind the bars; the L-axis is drawn after them (below) so a bar doesn't paint over
    // the baseline where it meets the axis.
    if (showGrid) {
        drawGrid(baseDrawCtx, {
            gridColor: theme.gridColor,
            gridDash: theme.gridDashPattern,
            frame: !showAxisLines,
            orientation: isHorizontal ? 'horizontal' : 'vertical',
            // In the axis-line style only the value-axis grid guides reading; category lines
            // through the band gaps are noise (line charts never draw them either).
            categoryTicks: showAxisLines ? [] : computeGridTicks(d3Scales, drawLabels, isHorizontal, xTickFormatter),
        })
    }

    const seriesBars = buildBarLayers({
        series: coloredSeries,
        labels: drawLabels,
        scales: d3Scales,
        layout: barLayout,
        isHorizontal,
        stackedData,
        topStackedKeyByAxis,
    })

    // Stacked cap rounding is re-resolved per band from the laid-out rects, so breakdown and
    // diverging stacks round their actual outer segments. Pills own the corners under
    // roundStackEnds, so skip there.
    if (barLayout !== 'grouped' && !roundStackEnds) {
        roundOuterStackCaps(
            seriesBars.flatMap((sb) => sb.bars),
            isHorizontal,
            d3Scales.value(0)
        )
    }

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

    if (showAxisLines) {
        drawAxes(baseDrawCtx, { axisColor: resolveAxisLineColor(theme) })
    }
}

export interface DrawBarHoverArgs {
    alpha: number
    barCornerRadius: number
    barTrack: boolean
    isHorizontal: boolean
}

/** Paint the resolved hover highlight. Track highlights draw a translucent full-extent rect; bar
 *  highlights draw a darker shade of the bar color. Clips to the pills from
 *  `resolveBarHoverItems` when rounding stack ends. */
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
            const highlightColor = d3Color(barColor)?.darker(BAR_HIGHLIGHT_DARKEN).toString() ?? barColor
            drawBarHighlight(ctx, bar, highlightColor, highlightRadius)
        }
    }
    ctx.restore()
}
