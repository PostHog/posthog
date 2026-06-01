import * as d3 from 'd3'
import React, { useCallback, useMemo, useRef } from 'react'

import { type BarChartPrivate, computeBarTrackRect, computeSeriesBars } from '../../core/bar-layout'
import {
    BAR_TRACK_HOVER_ALPHA,
    type BarRect,
    type BarRoundedCorners,
    type BarShadow,
    drawBarHighlight,
    drawBars,
    drawBarTracks,
    drawGrid,
    drawSolidBarTracks,
    type DrawContext,
    clipToRoundedRects,
} from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { DEFAULT_MARGINS, X_AXIS_TITLE_MARGIN } from '../../core/hooks/useChartMargins'
import { useLatest } from '../../core/hooks/useLatest'
import {
    buildSegmentResolveValue,
    buildStackedPositionValue,
    type BarScaleSet,
    computeDivergingStackData,
    computePercentStackData,
    computeStackData,
    createBarScales,
    type StackedBand,
    yTickCountForHeight,
} from '../../core/scales'
import type {
    BarChartConfig,
    BarsConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    DrawHoverResult,
    PointClickData,
    ResolvedSeries,
    Series,
    TooltipContext,
} from '../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../core/types'
import { computeVisibleXLabels } from '../../overlays/AxisLabels'
import { BarTooltip } from './BarTooltip'
import {
    type BarLayout,
    barContainsPointOnBandAxis,
    computeStackEdges,
    cursorOutsideBarFillExtent,
    findVisibleStackedSegment,
    iterBarsAtCursor,
    isStackedLayout,
    type StackEdges,
} from './utils/bars-under-cursor'

function bandCenter(scales: BarChartPrivate['__barChart'], label: string): number | undefined {
    const start = scales.band(label)
    return start == null ? undefined : start + scales.band.bandwidth() / 2
}

const ALL_CORNERS: BarRoundedCorners = { topLeft: true, topRight: true, bottomLeft: true, bottomRight: true }

/** One track rect per unique band, spanning the full value axis behind the stack. */
function computeBandTrackRects(
    scales: BarChartPrivate['__barChart'],
    labels: string[],
    isHorizontal: boolean
): BarRect[] {
    const [axisA = 0, axisB = 0] = scales.value.range()
    const valueMin = Math.min(axisA, axisB)
    const valueSize = Math.abs(axisB - axisA)
    const bandwidth = scales.band.bandwidth()
    const rects: BarRect[] = []
    for (const label of new Set(labels)) {
        const bandStart = scales.band(label)
        if (bandStart == null) {
            continue
        }
        rects.push(
            isHorizontal
                ? { x: valueMin, y: bandStart, width: valueSize, height: bandwidth, corners: ALL_CORNERS, dataIndex: 0 }
                : { x: bandStart, y: valueMin, width: bandwidth, height: valueSize, corners: ALL_CORNERS, dataIndex: 0 }
        )
    }
    return rects
}

/** Whether a cursor sits within a band's slot on the band axis (anywhere in that row's track). */
function cursorInBandTrack(
    scales: BarChartPrivate['__barChart'],
    label: string,
    cursor: { x: number; y: number },
    isHorizontal: boolean
): boolean {
    const bandStart = scales.band(label)
    if (bandStart == null) {
        return false
    }
    const bandCoord = isHorizontal ? cursor.y : cursor.x
    return bandCoord >= bandStart && bandCoord < bandStart + scales.band.bandwidth()
}

/** Center of a specific series's bar within a band. Used by overlays (e.g. annotations)
 *  to anchor on the current-period bar in compare-against-previous grouped layouts.
 *  Returns undefined when the layout isn't grouped or the series isn't in the group scale. */
function groupedBarCenter(scales: BarChartPrivate['__barChart'], label: string, seriesKey: string): number | undefined {
    const start = scales.band(label)
    const groupOffset = scales.group?.(seriesKey)
    if (start == null || groupOffset == null) {
        return undefined
    }
    return start + groupOffset + (scales.group?.bandwidth() ?? 0) / 2
}

export interface BarChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: BarChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

// Negative offsetY casts the shadow upward onto the visible track above the bar.
const DEFAULT_BAR_SHADOW: BarShadow = { color: 'rgba(0,0,0,0.30)', blur: 12, offsetY: -4 }

// Horizontal floor: each row gets at least this much px so tick labels don't crush; wrapper scrolls.
const HORIZONTAL_MIN_BAND_SIZE_DEFAULT = 24
// Reserve room for chart-edge margins + worst-case x-axis title margin (matches useChartMargins).
const HORIZONTAL_CHART_MARGIN_PX = DEFAULT_MARGINS.top + DEFAULT_MARGINS.bottom + X_AXIS_TITLE_MARGIN

function resolveBarShadow(barShadow: BarsConfig['shadow']): BarShadow | undefined {
    if (barShadow === true) {
        return DEFAULT_BAR_SHADOW
    }
    if (barShadow === false || barShadow == null) {
        return undefined
    }
    return barShadow
}

export function BarChart<Meta = unknown>({ onError, ...rest }: BarChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <BarChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function BarChartInner<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    dataAttr,
    children,
}: Omit<BarChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        yScaleType = 'linear',
        showGrid = false,
        barLayout = 'stacked',
        axisOrientation = 'vertical',
        xTickFormatter,
    } = config ?? {}
    const {
        cornerRadius = 0,
        rounding = 'cap',
        track,
        shadow: barShadow,
        divergingStack = false,
        maxBandRange,
        bandPadding,
        minBandSize,
    } = config?.bars ?? {}
    const roundStackBaseline = rounding === 'pill'
    const barCornerRadius = rounding === 'none' ? 0 : cornerRadius
    const barTrack = !!track
    const barTrackColor = typeof track === 'object' ? track.color : undefined
    const isHorizontal = axisOrientation === 'horizontal'

    const resolvedMinBandSize = minBandSize ?? (isHorizontal ? HORIZONTAL_MIN_BAND_SIZE_DEFAULT : 0)
    const wrapperMinHeight = useMemo(() => {
        if (!isHorizontal || resolvedMinBandSize <= 0) {
            return undefined
        }
        const uniqueBands = new Set(labels).size
        if (uniqueBands === 0) {
            return undefined
        }
        return uniqueBands * resolvedMinBandSize + HORIZONTAL_CHART_MARGIN_PX
    }, [isHorizontal, resolvedMinBandSize, labels])

    const stackedData = useMemo((): Map<string, StackedBand> | undefined => {
        if (barLayout === 'percent') {
            return computePercentStackData(series, labels)
        }
        if (barLayout === 'stacked') {
            return divergingStack ? computeDivergingStackData(series, labels) : computeStackData(series, labels)
        }
        return undefined
    }, [barLayout, series, labels, divergingStack])

    // Cap rounding is per-axis: buildStackData stacks each yAxisId independently, so each
    // axis has its own topmost visible series. Iteration order matches d3.stack's key order,
    // so the last write per axis is that axis's top layer.
    const topStackedKeyByAxis = useMemo<Map<string, string>>(() => {
        const m = new Map<string, string>()
        if (barLayout === 'grouped') {
            return m
        }
        for (const s of series) {
            if (s.visibility?.excluded) {
                continue
            }
            const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
            m.set(axisId, s.key)
        }
        return m
    }, [barLayout, series])

    const stackEdges = useMemo<StackEdges | undefined>(
        () => (roundStackBaseline && barLayout !== 'grouped' ? computeStackEdges(series, labels.length) : undefined),
        [roundStackBaseline, barLayout, series, labels.length]
    )

    const chartConfig = useMemo<BarChartConfig>(() => {
        const base = { ...config, isPercent: barLayout === 'percent' }
        if (barLayout !== 'percent' || config?.yTickFormatter) {
            return base
        }
        return {
            ...base,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, barLayout])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            // For stacked/percent, the value-axis domain must reflect cumulative sums, not
            // individual series ranges — pass a synthetic series whose data is each layer's top.
            // Diverging stacks also need each layer's bottom so negative columns extend the domain
            // below 0 (the bottom of a positive-only stack is always 0, but a diverging stack with
            // negative values pushes the bottom below 0).
            let stackedSeries: Series[] | undefined
            if (stackedData && barLayout === 'stacked') {
                stackedSeries = coloredSeries.flatMap((s) => {
                    const band = stackedData.get(s.key)
                    if (!band) {
                        return [s]
                    }
                    if (divergingStack) {
                        return [
                            { ...s, data: band.top },
                            { ...s, key: `${s.key}__bottom`, data: band.bottom },
                        ]
                    }
                    return [{ ...s, data: band.top }]
                })
            }

            const d3Scales = createBarScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                barLayout,
                axisOrientation,
                stackedSeries,
                maxBandRange,
                bandPadding,
            })

            const tickAxisLength = isHorizontal ? dimensions.plotWidth : dimensions.plotHeight
            const yTickCount = yTickCountForHeight(tickAxisLength)

            // Stash the raw d3 scales in the private slot so drawStatic/drawHover/click routing
            // can read them from the committed ChartScales — every render gets a self-contained
            // object, which avoids strict-mode / concurrent-rendering races.
            const barChartPrivate: BarChartPrivate = { __barChart: d3Scales }

            // For horizontal, expose the value scale as `y` (since AxisLabels horizontal mode
            // calls `scales.y(tick)` for x-pixel positioning of value ticks).
            // For vertical, `y` is the value scale on the y-axis.
            return {
                x: (label: string, seriesKey?: string) => {
                    if (seriesKey != null && barLayout === 'grouped') {
                        const xForSeries = groupedBarCenter(d3Scales, label, seriesKey)
                        if (xForSeries != null) {
                            return xForSeries
                        }
                    }
                    return bandCenter(d3Scales, label)
                },
                y: (value: number) => d3Scales.value(value),
                yTicks: () => d3Scales.value.ticks?.(yTickCount) ?? [],
                // Width of the rendered bar content within the band. In grouped mode the
                // bars sit inside group outer padding, so `band.bandwidth()` overshoots
                // the rightmost bar's right edge and anchors the tooltip in empty space.
                extent: () => {
                    if (isHorizontal) {
                        return undefined
                    }
                    const groupScale = d3Scales.group
                    if (barLayout === 'grouped' && groupScale) {
                        const domain = groupScale.domain()
                        if (domain.length > 0) {
                            const firstOffset = groupScale(domain[0]) ?? 0
                            const lastOffset = groupScale(domain[domain.length - 1]) ?? 0
                            const contentExtent = lastOffset + groupScale.bandwidth() - firstOffset
                            if (contentExtent > 0) {
                                return contentExtent
                            }
                        }
                    }
                    return d3Scales.band.bandwidth()
                },
                _private: barChartPrivate,
            }
        },
        [yScaleType, barLayout, axisOrientation, stackedData, isHorizontal, divergingStack, maxBandRange, bandPadding]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
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
                    const topAtIndex = stackEdges?.topKeyAtIndex.get(axisId)
                    const bottomAtIndex = stackEdges?.bottomKeyAtIndex.get(axisId)
                    const bars = computeSeriesBars({
                        series: s,
                        labels: drawLabels,
                        scales: d3Scales,
                        layout: barLayout,
                        isHorizontal,
                        stackedBand: stackedData?.get(s.key),
                        isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
                        capRoundedAtIndex: stackEdges ? (i) => topAtIndex?.[i] === s.key : undefined,
                        baseRoundedAtIndex:
                            stackEdges && roundStackBaseline ? (i) => bottomAtIndex?.[i] === s.key : undefined,
                    }).filter((b): b is BarRect => b !== null)
                    return { series: s, bars }
                })

            if (barTrack && barLayout === 'grouped') {
                const [axisStart = 0, axisEnd = 0] = d3Scales.value.range()
                for (const { series: s, bars } of seriesBars) {
                    const tracks = bars.map((b) => computeBarTrackRect(b, axisStart, axisEnd, isHorizontal))
                    drawBarTracks(baseDrawCtx, s, tracks, barCornerRadius)
                }
            } else if (barTrack) {
                const tracks = computeBandTrackRects(d3Scales, drawLabels, isHorizontal)
                drawSolidBarTracks(
                    ctx,
                    tracks,
                    barTrackColor ?? theme.gridColor ?? 'rgba(0, 0, 0, 0.08)',
                    barCornerRadius
                )
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
            // Pill mode: clip the stack to the rounded band so a too-thin edge segment still rounds.
            const pillClip = roundStackBaseline && isStackedLayout(barLayout)
            if (pillClip) {
                ctx.save()
                clipToRoundedRects(ctx, computeBandTrackRects(d3Scales, drawLabels, isHorizontal), barCornerRadius)
            }
            for (const { series: s, bars } of seriesBars) {
                drawBars(baseDrawCtx, s, bars, barCornerRadius)
            }
            if (pillClip) {
                ctx.restore()
            }
            if (resolvedShadow) {
                ctx.restore()
            }
        },
        [
            showGrid,
            stackedData,
            barLayout,
            isHorizontal,
            topStackedKeyByAxis,
            stackEdges,
            roundStackBaseline,
            barCornerRadius,
            barTrack,
            barTrackColor,
            theme.gridColor,
            xTickFormatter,
            barShadow,
        ]
    )

    // Restart the fade on bar → track moves (same hoverIndex, different visible state).
    const lastHoverKeyRef = useRef<string | null>(null)

    const drawHover = useCallback(
        ({
            ctx,
            scales,
            series: coloredSeries,
            labels: drawLabels,
            hoverIndex,
            hoverPosition,
            hoverProgress,
            resetHoverFade,
        }: ChartDrawArgs): DrawHoverResult => {
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales || hoverIndex < 0) {
                lastHoverKeyRef.current = null
                return false
            }
            const hoveredLabel = drawLabels[hoverIndex]
            const [trackAxisStart = 0, trackAxisEnd = 0] = barTrack ? d3Scales.value.range() : []
            // Key includes bar-vs-track per series so bar → track moves at the same
            // hoverIndex still trigger a fade restart.
            type DrawItem = { series: ResolvedSeries; bar: BarRect; isTrackHighlight: boolean }
            const items: DrawItem[] = []
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
                    stackEdges,
                    roundStackBaseline,
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
                    stackEdges,
                    roundStackBaseline,
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
                lastHoverKeyRef.current = null
                return false
            }
            const currentKey = `${hoverIndex}:${composition}`
            let alpha = hoverProgress
            if (currentKey !== lastHoverKeyRef.current) {
                alpha = resetHoverFade()
                lastHoverKeyRef.current = currentKey
            }
            ctx.save()
            ctx.globalAlpha = alpha
            if (roundStackBaseline && stackedHighlight) {
                clipToRoundedRects(ctx, computeBandTrackRects(d3Scales, drawLabels, isHorizontal), barCornerRadius)
            }
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
            ctx.restore()
            return true
        },
        [
            stackedData,
            barLayout,
            isHorizontal,
            topStackedKeyByAxis,
            stackEdges,
            roundStackBaseline,
            barCornerRadius,
            barTrack,
        ]
    )

    // Show each series's own segment value (resolveValue) but anchor the tooltip/value labels
    // at the stacked top (resolvePositionValue) so a stacked bar doesn't read as a running total.
    const resolveValue = useMemo(() => buildSegmentResolveValue(stackedData), [stackedData])
    const resolvePositionValue = useMemo(() => buildStackedPositionValue(stackedData), [stackedData])

    const seriesRef = useLatest(series)
    const labelsRef = useLatest(labels)

    // Bars sharing a band slot — rewrite the click payload to the series actually under the
    // cursor so drop-off fillers and per-breakdown segments route correctly.
    const wrapClickData = useCallback(
        (clickData: PointClickData<Meta>, scales: ChartScales): PointClickData<Meta> => {
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales) {
                return clickData
            }
            return (
                resolveClickedBarSeries({
                    clickData,
                    d3Scales,
                    barLayout,
                    isHorizontal,
                    stackedData,
                    topStackedKeyByAxis,
                    series: seriesRef.current,
                    labels: labelsRef.current,
                    barTrack,
                }) ?? clickData
            )
        },
        [barLayout, isHorizontal, stackedData, topStackedKeyByAxis, seriesRef, labelsRef, barTrack]
    )

    const chart = (
        <Chart
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={(ctx) => (
                <BarTooltip<Meta>
                    ctx={ctx}
                    userTooltip={tooltip}
                    allSeries={series}
                    stackedData={stackedData}
                    topStackedKeyByAxis={topStackedKeyByAxis}
                    layout={barLayout}
                    isHorizontal={isHorizontal}
                />
            )}
            onPointClick={onPointClick}
            wrapClickData={onPointClick ? wrapClickData : undefined}
            className={className}
            dataAttr={dataAttr}
            resolveValue={resolveValue}
            resolvePositionValue={resolvePositionValue}
        >
            {children}
        </Chart>
    )

    // Always wrap — switching shape (axisOrientation, empty labels) would otherwise remount Chart.
    return (
        <div className="flex flex-col flex-1" style={{ minHeight: wrapperMinHeight }}>
            {chart}
        </div>
    )
}

/** Rewrites the click payload to the bar series actually under the cursor. The base payload
 *  always points at the first series in the band; this picks the right one per layout:
 *   - grouped: the series whose sub-band column the cursor is over — band axis only, so a
 *     click above a short bar (or on its track) still resolves to that column.
 *   - stacked/percent: the segment whose rect contains the cursor on the value axis, walking
 *     every dataIndex in the band so sparse-overlap segments route correctly, and re-reading
 *     the value at that segment's own dataIndex.
 *  Pure so the routing is unit-testable; returns `null` to pass `clickData` through unchanged. */
export function resolveClickedBarSeries<Meta>({
    clickData,
    d3Scales,
    barLayout,
    isHorizontal,
    stackedData,
    topStackedKeyByAxis,
    series,
    labels,
    barTrack,
}: {
    clickData: PointClickData<Meta>
    d3Scales: BarScaleSet
    barLayout: BarLayout
    isHorizontal: boolean
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    series: Series<Meta>[]
    labels: readonly string[]
    barTrack: boolean
}): PointClickData<Meta> | null {
    const { cursor, label, dataIndex, crossSeriesData } = clickData
    if (!cursor) {
        return null
    }
    const rewrite = (hitSeries: Series<Meta>, value: number, hitDataIndex: number): PointClickData<Meta> => ({
        ...clickData,
        dataIndex: hitDataIndex,
        series: hitSeries,
        value,
        seriesIndex: series.findIndex((s) => s.key === hitSeries.key),
    })

    if (barLayout === 'grouped') {
        for (const { series: s, bar } of iterBarsAtCursor({
            series: crossSeriesData.map((d) => d.series),
            label,
            dataIndex,
            scales: d3Scales,
            layout: barLayout,
            isHorizontal,
            topStackedKeyByAxis,
        })) {
            if (!barContainsPointOnBandAxis(bar, cursor, isHorizontal)) {
                continue
            }
            const hit = crossSeriesData.find((d) => d.series.key === s.key)
            return hit ? rewrite(hit.series, hit.value, dataIndex) : null
        }
        return null
    }

    const visible = findVisibleStackedSegment({
        series: crossSeriesData.map((d) => d.series),
        labels,
        hoveredLabel: label,
        cursor,
        scales: d3Scales,
        layout: barLayout,
        isHorizontal,
        stackedData,
        topStackedKeyByAxis,
    })
    if (!visible) {
        // No filled segment under the cursor — a click in a tracked band's empty remainder.
        if (barTrack && cursorInBandTrack(d3Scales, label, cursor, isHorizontal)) {
            return { ...clickData, inTrack: true }
        }
        return null
    }
    const hit = crossSeriesData.find((d) => d.series.key === visible.series.key)
    if (!hit) {
        return null
    }
    // Re-read value at the visible segment's own dataIndex — `hit.value` was resolved at the
    // band's dataIndex, which is a sparse-zero cell for the visible series.
    const raw = hit.series.data[visible.dataIndex]
    const resolvedValue = typeof raw === 'number' && Number.isFinite(raw) ? raw : hit.value
    return rewrite(hit.series, resolvedValue, visible.dataIndex)
}
