import * as d3 from 'd3'
import React, { useCallback, useMemo } from 'react'

import { type BarChartPrivate, computeBarAtIndex, computeBarTrackRect, computeSeriesBars } from '../../core/bar-layout'
import {
    BAR_TRACK_HOVER_ALPHA,
    type BarRect,
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
                _private: barChartPrivate,
            }
        },
        [yScaleType, barLayout, axisOrientation, stackedData, isHorizontal, divergingStack]
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

            for (const { series: s, bars } of seriesBars) {
                drawBars(baseDrawCtx, s, bars, barCornerRadius)
            }
        },
        [showGrid, stackedData, barLayout, isHorizontal, topStackedKeyByAxis, barCornerRadius, barTrack, xTickFormatter]
    )

    const drawHover = useCallback(
        ({ ctx, scales, series: coloredSeries, labels: drawLabels, hoverIndex, hoverPosition }: ChartDrawArgs) => {
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales || hoverIndex < 0) {
                return
            }
            const hoveredLabel = drawLabels[hoverIndex]
            // Hoisted out of the per-series loop below — the value-axis range doesn't
            // depend on which series the cursor is over.
            const [trackAxisStart = 0, trackAxisEnd = 0] = barTrack ? d3Scales.value.range() : []
            // Narrow to bars whose band-axis extent contains the cursor; an empty hit set
            // means the cursor is in a gap, so draw nothing.
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
                    return
                }
                hitKeys = hits
            }
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
                // Over the track region above the bar: highlight the track instead of the bar.
                // A translucent series-color fill leaves the opaque bar unchanged but tints
                // the faint hatched track.
                if (
                    barTrack &&
                    barLayout === 'grouped' &&
                    hoverPosition &&
                    cursorOutsideBarFillExtent(bar, hoverPosition, isHorizontal)
                ) {
                    const parsed = d3.color(s.color)
                    // Always translucent — falling back to `s.color` directly would paint
                    // an opaque full-plot-height block if d3 can't parse the series color.
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
