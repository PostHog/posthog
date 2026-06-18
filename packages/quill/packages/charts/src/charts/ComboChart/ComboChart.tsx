import { color as d3Color } from 'd3-color'
import React, { useCallback, useMemo } from 'react'

import { bandCenter, computeBarAtIndex, computeSeriesBars, groupedBarCenter } from '../../core/bar-layout'
import {
    type BarRect,
    DEFAULT_BAR_CORNER_RADIUS,
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
import { barColorAt } from '../../core/color-utils'
import {
    type ComboChartPrivate,
    createComboScales,
    partitionByType,
    resolveComboYScale,
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
    DrawHoverResult,
    PointClickData,
    ResolvedSeries,
    Series,
    SeriesType,
    TooltipContext,
    YAxisScale,
} from '../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../core/types'
import { computeVisibleXLabels } from '../../overlays/AxisLabels'
import { resolveBarsAtCursor } from '../BarChart/utils/bars-under-cursor'
import { ComboTooltip } from './ComboTooltip'

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
        barCornerRadius = DEFAULT_BAR_CORNER_RADIUS,
        defaultSeriesType = 'line',
        xTickFormatter,
    } = config ?? {}

    const seriesTypeOf = useCallback(
        (s: Pick<Series, 'type'>): SeriesType => resolveSeriesType(s, defaultSeriesType),
        [defaultSeriesType]
    )

    // Stack only bar series together. Lines/areas are explicitly excluded so a line doesn't get a
    // bottom-of-stack offset and bars don't widen the line's drawn baseline.
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

    // Per-axis topmost bar — only bar layers below the cap forgo corner rounding. Non-bar series
    // are skipped since lines/areas don't participate in bar stacking. Last write per axis wins,
    // matching d3.stack's key order (mirrors BarChart's topStackedKeyByAxis).
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

            // Pre-index series by key so the grouped `x` closure resolves seriesKey → type in O(1)
            // instead of scanning the array on every overlay/value-label call.
            const seriesByKey = new Map<string, ResolvedSeries>()
            for (const s of coloredSeries) {
                seriesByKey.set(s.key, s)
            }

            const comboPrivate: ComboChartPrivate = { __comboChart: comboScales }

            return {
                x: (label: string, seriesKey?: string) => {
                    if (seriesKey != null && barLayout === 'grouped') {
                        // Only bars use the group scale; lines/areas fall through to band center.
                        const s = seriesByKey.get(seriesKey)
                        if (s && seriesTypeOf(s) === 'bar') {
                            const xForSeries = groupedBarCenter(comboScales, label, seriesKey)
                            if (xForSeries != null) {
                                return xForSeries
                            }
                        }
                    }
                    return bandCenter(comboScales, label)
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
                xScale: (label) => bandCenter(comboScales, label),
                yScale: comboScales.y,
                labels: drawLabels,
            }

            if (showGrid) {
                const categoryTicks = computeVisibleXLabels(
                    drawLabels,
                    (label) => bandCenter(comboScales, label),
                    xTickFormatter
                ).map((entry) => entry.x)
                drawGrid(baseDrawCtx, { gridColor: theme.gridColor, categoryTicks })
            }

            // ── 1. Bars ───────────────────────────────────────────────────────────────
            for (const s of barSeries) {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const perSeriesScales: BarScaleSet = {
                    band: comboScales.band,
                    value: resolveComboYScale(comboScales, s),
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

            // ── 2. Area fills first, then lines + points. Two passes so every area sits below
            //      every line regardless of input order — a single per-series loop would paint a
            //      later area over an earlier line. Clip vertically so out-of-domain values stay
            //      out of the axis gutters while edge markers/caps still render whole.
            const CLIP_PAD = 8
            ctx.save()
            ctx.beginPath()
            ctx.rect(0, dimensions.plotTop - CLIP_PAD, dimensions.width, dimensions.plotHeight + CLIP_PAD * 2)
            ctx.clip()
            for (const s of lineSeries) {
                if (seriesTypeOf(s) !== 'area' && !s.fill) {
                    continue
                }
                drawArea(
                    { ...baseDrawCtx, yScale: resolveComboYScale(comboScales, s) },
                    s,
                    undefined,
                    s.fill?.lowerData
                )
            }
            for (const s of lineSeries) {
                if (s.fill?.lowerData) {
                    continue
                }
                const drawCtx: DrawContext = { ...baseDrawCtx, yScale: resolveComboYScale(comboScales, s) }
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
        }: ChartDrawArgs): DrawHoverResult => {
            if (hoverIndex < 0) {
                return false
            }
            const comboScales = (scales._private as ComboChartPrivate | undefined)?.__comboChart
            if (!comboScales) {
                return false
            }

            const hoveredLabel = drawLabels[hoverIndex]
            const { bars: barSeries, lines: lineSeries } = partitionByType(coloredSeries, seriesTypeOf)
            let drewAny = false

            // Bars: only highlight those whose band-axis extent contains the cursor. The hit set is
            // band-axis only, so the shared bar resolver works directly on the combo scales.
            const barHits = hoverPosition
                ? resolveBarsAtCursor({
                      series: barSeries,
                      label: hoveredLabel,
                      dataIndex: hoverIndex,
                      cursor: hoverPosition,
                      scales: comboScales,
                      layout: barLayout,
                      isHorizontal: false,
                      stackedData: barStackedData,
                      topStackedKeyByAxis,
                  }).hits
                : null

            for (const s of barSeries) {
                if (barHits && !barHits.has(s.key)) {
                    continue
                }
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const perSeriesScales: BarScaleSet = {
                    band: comboScales.band,
                    value: resolveComboYScale(comboScales, s),
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
                const barColor = barColorAt(s, bar.dataIndex)
                const highlightColor = d3Color(barColor)?.darker(0.6).toString() ?? barColor
                drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
                drewAny = true
            }

            // Lines/areas — highlight ring at the band center for this index. Auxiliary overlays
            // (trendlines, moving averages) opt out: they shouldn't surface as primary points on
            // hover. Mirrors LineChart.drawHover.
            const x = bandCenter(comboScales, hoveredLabel)
            if (x == null) {
                return drewAny
            }
            for (const s of lineSeries) {
                if (s.fill?.lowerData || s.overlay) {
                    continue
                }
                const raw = s.data[hoverIndex]
                if (raw == null || !isFinite(raw)) {
                    continue
                }
                const y = resolveComboYScale(comboScales, s)(raw)
                if (isFinite(y)) {
                    drawHighlightPoint(ctx, x, y, s.color, theme.backgroundColor ?? '#ffffff')
                    drewAny = true
                }
            }
            return drewAny
        },
        [seriesTypeOf, barLayout, barStackedData, topStackedKeyByAxis, barCornerRadius]
    )

    // Bar segments report their own value; lines report raw. buildSegmentResolveValue's fallback
    // handles non-bar series automatically (they aren't in barStackedData), so the bar-only stack
    // still yields correct line values.
    const resolveValue = useMemo(() => buildSegmentResolveValue(barStackedData), [barStackedData])
    const resolvePositionValue = useMemo(() => buildStackedPositionValue(barStackedData), [barStackedData])

    const renderTooltip = useCallback(
        (ctx: TooltipContext<Meta>) => (
            <ComboTooltip<Meta>
                ctx={ctx}
                userTooltip={tooltip}
                barStackedData={barStackedData}
                topStackedKeyByAxis={topStackedKeyByAxis}
                layout={barLayout}
                defaultSeriesType={defaultSeriesType}
            />
        ),
        [tooltip, barStackedData, topStackedKeyByAxis, barLayout, defaultSeriesType]
    )

    return (
        <Chart
            series={series}
            labels={labels}
            config={config}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={renderTooltip}
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
