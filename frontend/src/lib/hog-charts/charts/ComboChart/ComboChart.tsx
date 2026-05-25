import * as d3 from 'd3'
import React, { useCallback, useMemo } from 'react'

import { computeBarAtIndex, computeSeriesBars } from '../../core/bar-layout'
import {
    type BarRect,
    drawArea,
    drawBarHighlight,
    drawBars,
    drawGrid,
    drawHighlightPoint,
    drawLine,
    drawPoints,
    type DrawContext,
} from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import {
    type ComboChartPrivate,
    type ComboScaleSet,
    createComboScales,
    partitionByType,
    resolveSeriesType,
} from '../../core/combo-scales'
import {
    type BarScaleSet,
    buildSegmentResolveValue,
    buildStackedPositionValue,
    computeStackData,
    type StackedBand,
    yTickCountForHeight,
} from '../../core/scales'
import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    ComboChartConfig,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    Series,
    SeriesType,
    TooltipContext,
    YAxisScale,
} from '../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../core/types'
import { computeVisibleXLabels } from '../../overlays/AxisLabels'
import { ComboTooltip } from './ComboTooltip'
import { barKeysAtCursor } from './utils/combo-bar-hit'

export interface ComboChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: ComboChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function ComboChart<Meta = unknown>({ onError, ...rest }: ComboChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <ComboChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function bandCenter(band: d3.ScaleBand<string>, label: string): number | undefined {
    const start = band(label)
    return start == null ? undefined : start + band.bandwidth() / 2
}

function groupedBarCenter(scales: ComboScaleSet, label: string, seriesKey: string): number | undefined {
    const start = scales.band(label)
    const groupOffset = scales.group?.(seriesKey)
    if (start == null || groupOffset == null) {
        return undefined
    }
    return start + groupOffset + (scales.group?.bandwidth() ?? 0) / 2
}

function ComboChartInner<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    dataAttr,
    children,
}: Omit<ComboChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        yScaleType = 'linear',
        showGrid = false,
        barLayout = 'stacked',
        barCornerRadius = 4,
        defaultSeriesType = 'line',
        xTickFormatter,
    } = config ?? {}

    const seriesTypeOf = useCallback(
        (s: Pick<Series, 'type'>): SeriesType => resolveSeriesType(s, defaultSeriesType),
        [defaultSeriesType]
    )

    // Stack only bar series together. Lines/areas are explicitly excluded so a line doesn't
    // get a bottom-of-stack offset and bars don't widen the line's drawn baseline.
    const barStackedData = useMemo<Map<string, StackedBand> | undefined>(() => {
        if (barLayout !== 'stacked') {
            return undefined
        }
        const barSeries = series.filter((s) => seriesTypeOf(s) === 'bar')
        if (barSeries.length === 0) {
            return undefined
        }
        return computeStackData(barSeries, labels)
    }, [barLayout, series, labels, seriesTypeOf])

    // Per-axis topmost bar — only bar layers below the cap forgo corner rounding.
    const topStackedKeyByAxis = useMemo<Map<string, string>>(() => {
        const m = new Map<string, string>()
        if (barLayout !== 'stacked') {
            return m
        }
        for (const s of series) {
            if (s.visibility?.excluded || seriesTypeOf(s) !== 'bar') {
                continue
            }
            m.set(s.yAxisId ?? DEFAULT_Y_AXIS_ID, s.key)
        }
        return m
    }, [barLayout, series, seriesTypeOf])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const comboScales = createComboScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                barLayout,
                seriesTypeOf,
                barStackedData,
            })

            const yTickCount = yTickCountForHeight(dimensions.plotHeight)
            const yAxes: Record<string, YAxisScale> = {}
            for (const [axisId, { scale, position }] of Object.entries(comboScales.yAxes)) {
                yAxes[axisId] = {
                    scale: (v: number) => scale(v),
                    ticks: () => scale.ticks?.(yTickCount) ?? [],
                    position,
                }
            }

            const comboPrivate: ComboChartPrivate = { __comboChart: comboScales }

            return {
                x: (label: string, seriesKey?: string) => {
                    if (seriesKey != null && barLayout === 'grouped') {
                        // Find the series — only bars use the group scale; lines/areas fall through.
                        const s = coloredSeries.find((c) => c.key === seriesKey)
                        if (s && seriesTypeOf(s) === 'bar') {
                            const xForSeries = groupedBarCenter(comboScales, label, seriesKey)
                            if (xForSeries != null) {
                                return xForSeries
                            }
                        }
                    }
                    return bandCenter(comboScales.band, label)
                },
                y: (v: number) => comboScales.y(v),
                yTicks: () => comboScales.y.ticks?.(yTickCount) ?? [],
                yAxes,
                _private: comboPrivate,
            }
        },
        [yScaleType, barLayout, seriesTypeOf, barStackedData]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
            const comboScales = (scales._private as ComboChartPrivate | undefined)?.__comboChart
            if (!comboScales) {
                return
            }

            const { bars: barSeries, lines: lineSeries } = partitionByType(coloredSeries, seriesTypeOf)

            const baseDrawCtx: DrawContext = {
                ctx,
                dimensions,
                xScale: (label) => bandCenter(comboScales.band, label),
                yScale: comboScales.y,
                labels: drawLabels,
            }

            if (showGrid) {
                const categoryTicks = computeVisibleXLabels(
                    drawLabels,
                    (label) => bandCenter(comboScales.band, label),
                    xTickFormatter
                ).map((entry) => entry.x)
                drawGrid(baseDrawCtx, { gridColor: theme.gridColor, categoryTicks })
            }

            // ── 1. Bars ───────────────────────────────────────────────────────────────
            for (const s of barSeries) {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const valueScale = comboScales.yAxes[axisId]?.scale ?? comboScales.y
                const perSeriesScales: BarScaleSet = {
                    band: comboScales.band,
                    value: valueScale,
                    group: comboScales.group,
                }
                const bars = computeSeriesBars({
                    series: s,
                    labels: drawLabels,
                    scales: perSeriesScales,
                    layout: barLayout,
                    isHorizontal: false,
                    stackedBand: barStackedData?.get(s.key),
                    isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
                }).filter((b): b is BarRect => b !== null)
                drawBars(baseDrawCtx, s, bars, barCornerRadius)
            }

            // Lines/areas — clip to plot so an overlay projecting below 0 doesn't paint into the gutter.
            const CLIP_PAD = 8
            ctx.save()
            ctx.beginPath()
            ctx.rect(
                dimensions.plotLeft,
                dimensions.plotTop - CLIP_PAD,
                dimensions.plotWidth,
                dimensions.plotHeight + CLIP_PAD * 2
            )
            ctx.clip()

            // ── 2. Area fills first, then lines + points. Two passes so every area sits
            //      below every line regardless of input order — a single per-series loop
            //      would paint a later area over an earlier line.
            for (const s of lineSeries) {
                const stype = seriesTypeOf(s)
                if (stype !== 'area' && !s.fill) {
                    continue
                }
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const yScale = comboScales.yAxes[axisId]?.scale ?? comboScales.y
                drawArea({ ...baseDrawCtx, yScale }, s, undefined, s.fill?.lowerData)
            }
            for (const s of lineSeries) {
                if (s.fill?.lowerData) {
                    continue
                }
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const yScale = comboScales.yAxes[axisId]?.scale ?? comboScales.y
                const drawCtx: DrawContext = { ...baseDrawCtx, yScale }
                drawLine(drawCtx, s)
                drawPoints(drawCtx, s)
            }

            ctx.restore()
        },
        [seriesTypeOf, showGrid, xTickFormatter, barLayout, barStackedData, topStackedKeyByAxis, barCornerRadius]
    )

    const drawHover = useCallback(
        ({
            ctx,
            scales,
            series: coloredSeries,
            labels: drawLabels,
            hoverIndex,
            hoverPosition,
            theme,
        }: ChartDrawArgs) => {
            if (hoverIndex < 0) {
                return
            }
            const comboScales = (scales._private as ComboChartPrivate | undefined)?.__comboChart
            if (!comboScales) {
                return
            }

            const hoveredLabel = drawLabels[hoverIndex]

            // Bars: only highlight those whose band-axis extent contains the cursor.
            let barHits: Set<string> | null = null
            if (hoverPosition) {
                barHits = barKeysAtCursor({
                    series: coloredSeries,
                    label: hoveredLabel,
                    dataIndex: hoverIndex,
                    cursor: hoverPosition,
                    scales: comboScales,
                    layout: barLayout,
                    barStackedData,
                    topStackedKeyByAxis,
                    defaultSeriesType,
                })
            }

            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const stype = seriesTypeOf(s)
                if (stype === 'bar') {
                    if (barHits && !barHits.has(s.key)) {
                        continue
                    }
                    const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                    const valueScale = comboScales.yAxes[axisId]?.scale ?? comboScales.y
                    const perSeriesScales: BarScaleSet = {
                        band: comboScales.band,
                        value: valueScale,
                        group: comboScales.group,
                    }
                    const bar = computeBarAtIndex({
                        series: s,
                        label: hoveredLabel,
                        dataIndex: hoverIndex,
                        scales: perSeriesScales,
                        layout: barLayout,
                        isHorizontal: false,
                        stackedBand: barStackedData?.get(s.key),
                        isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
                    })
                    if (!bar) {
                        continue
                    }
                    const highlightColor = d3.color(s.color)?.darker(0.6).toString() ?? s.color
                    drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
                    continue
                }
                // Lines/areas — highlight ring at the band center for this index.
                if (s.fill?.lowerData) {
                    continue
                }
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const yScale = comboScales.yAxes[axisId]?.scale ?? comboScales.y
                const x = bandCenter(comboScales.band, hoveredLabel)
                const raw = s.data[hoverIndex]
                if (x == null || !isFinite(raw)) {
                    continue
                }
                const y = yScale(raw)
                if (isFinite(y)) {
                    drawHighlightPoint(ctx, x, y, s.color, theme.backgroundColor ?? '#ffffff')
                }
            }
        },
        [seriesTypeOf, barLayout, barStackedData, topStackedKeyByAxis, barCornerRadius, defaultSeriesType]
    )

    // Bar segments report their own value; lines report raw. buildSegmentResolveValue's fallback
    // handles non-bar series automatically (they aren't in barStackedData), so we can pass the
    // bar-only stack and still get correct line values.
    const resolveValue = useMemo(() => buildSegmentResolveValue(barStackedData), [barStackedData])
    const resolvePositionValue = useMemo(() => buildStackedPositionValue(barStackedData), [barStackedData])

    return (
        <Chart
            series={series}
            labels={labels}
            config={config}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={(ctx) => (
                <ComboTooltip<Meta>
                    ctx={ctx}
                    userTooltip={tooltip}
                    barStackedData={barStackedData}
                    topStackedKeyByAxis={topStackedKeyByAxis}
                    layout={barLayout}
                    defaultSeriesType={defaultSeriesType}
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
