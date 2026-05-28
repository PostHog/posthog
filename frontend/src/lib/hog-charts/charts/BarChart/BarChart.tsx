import * as d3 from 'd3'
import React, { useCallback, useMemo, useRef } from 'react'

import { type BarChartPrivate, computeBarAtIndex, computeBarTrackRect, computeSeriesBars } from '../../core/bar-layout'
import {
    BAR_TRACK_HOVER_ALPHA,
    type BarRect,
    type BarShadow,
    drawBarHighlight,
    drawBars,
    drawBarTracks,
    drawGrid,
    type DrawContext,
} from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import {
    buildSegmentResolveValue,
    buildStackedPositionValue,
    computeDivergingStackData,
    computePercentStackData,
    computeStackData,
    createBarScales,
    type StackedBand,
    yTickCountForHeight,
} from '../../core/scales'
import type {
    BarChartConfig,
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
import { cursorOutsideBarFillExtent, seriesKeysAtCursor } from './utils/bars-under-cursor'

function bandCenter(scales: BarChartPrivate['__barChart'], label: string): number | undefined {
    const start = scales.band(label)
    return start == null ? undefined : start + scales.band.bandwidth() / 2
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

function resolveBarShadow(barShadow: BarChartConfig['barShadow']): BarShadow | undefined {
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
        barCornerRadius = 0,
        barTrack = false,
        axisOrientation = 'vertical',
        xTickFormatter,
        divergingStack = false,
        maxBandRange,
        barShadow,
    } = config ?? {}
    const isHorizontal = axisOrientation === 'horizontal'

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
            })

            const tickAxisLength = isHorizontal ? dimensions.plotWidth : dimensions.plotHeight
            const yTickCount = yTickCountForHeight(tickAxisLength)

            // Stash the raw d3 scales in the private slot so drawStatic/drawHover can read them
            // without a side-channel ref — every render gets a self-contained ChartScales object,
            // which avoids strict-mode / concurrent-rendering races between createScales and the
            // static-draw effect. See LineChart.tsx and ARCHITECTURE.md for the canonical pattern.
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
        [yScaleType, barLayout, axisOrientation, stackedData, isHorizontal, divergingStack, maxBandRange]
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
        },
        [
            showGrid,
            stackedData,
            barLayout,
            isHorizontal,
            topStackedKeyByAxis,
            barCornerRadius,
            barTrack,
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
            let hitKeys: Set<string> | null = null
            if (hoverPosition) {
                const hits = seriesKeysAtCursor({
                    series: coloredSeries,
                    label: hoveredLabel,
                    dataIndex: hoverIndex,
                    cursor: hoverPosition,
                    scales: d3Scales,
                    layout: barLayout,
                    isHorizontal,
                    stackedData,
                    topStackedKeyByAxis,
                })
                if (hits.size === 0) {
                    lastHoverKeyRef.current = null
                    return false
                }
                hitKeys = hits
            }
            // Key includes bar-vs-track per series so bar → track moves at the same
            // hoverIndex still trigger a fade restart.
            type DrawItem = { series: ResolvedSeries; bar: BarRect; isTrackHighlight: boolean }
            const items: DrawItem[] = []
            let composition = ''
            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                if (hitKeys && !hitKeys.has(s.key)) {
                    continue
                }
                const stackedBand = stackedData?.get(s.key)
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const isTop = topStackedKeyByAxis.get(axisId) === s.key
                const bar = computeBarAtIndex({
                    series: s,
                    label: hoveredLabel,
                    dataIndex: hoverIndex,
                    scales: d3Scales,
                    layout: barLayout,
                    isHorizontal,
                    stackedBand,
                    isTopOfStack: isTop,
                })
                if (!bar) {
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
        [stackedData, barLayout, isHorizontal, topStackedKeyByAxis, barCornerRadius, barTrack]
    )

    // Show each series's own segment value (resolveValue) but anchor the tooltip/value labels
    // at the stacked top (resolvePositionValue) so a stacked bar doesn't read as a running total.
    const resolveValue = useMemo(() => buildSegmentResolveValue(stackedData), [stackedData])
    const resolvePositionValue = useMemo(() => buildStackedPositionValue(stackedData), [stackedData])

    return (
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
                    stackedData={stackedData}
                    topStackedKeyByAxis={topStackedKeyByAxis}
                    layout={barLayout}
                    isHorizontal={isHorizontal}
                />
            )}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
            resolveValue={resolveValue}
            resolvePositionValue={resolvePositionValue}
        >
            {children}
        </Chart>
    )
}
