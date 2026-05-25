import * as d3 from 'd3'
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
    withPlotClip,
} from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { type ComboChartPrivate, createComboScales, partitionByType, resolveSeriesType } from '../../core/combo-scales'
import {
    type BarScaleSet,
    buildSegmentResolveValue,
    buildStackedPositionValue,
    computeStackData,
    computeTopStackedKeyByAxis,
    resolveYScaleForSeries,
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

    // Per-axis topmost bar — only bar layers below the cap forgo corner rounding. Non-bar
    // series are excluded since lines/areas don't participate in bar stacking.
    const topStackedKeyByAxis = useMemo<Map<string, string>>(
        () =>
            barLayout !== 'stacked'
                ? new Map()
                : computeTopStackedKeyByAxis(series, { skip: (s) => seriesTypeOf(s) !== 'bar' }),
        [barLayout, series, seriesTypeOf]
    )

    // d3.color(...).darker() parsing runs on every mousemove for every bar without this.
    // Caching by `series.key` invalidates when the series prop identity changes (i.e. when
    // colors or series themselves change), which is the right granularity. Theme-fallback
    // colors are picked up from each draw's `coloredSeries`, not from the raw `series` prop —
    // callers without a `s.color` fall through to the live `s.color` per draw.
    const darkenedColors = useMemo<Map<string, string>>(() => {
        const m = new Map<string, string>()
        for (const s of series) {
            if (s.visibility?.excluded || seriesTypeOf(s) !== 'bar' || !s.color) {
                continue
            }
            m.set(s.key, d3.color(s.color)?.darker(0.6).toString() ?? s.color)
        }
        return m
    }, [series, seriesTypeOf])

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

            // Pre-index series by key so the `x` closure resolves seriesKey → bar lookup in O(1)
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
                            const xForSeries = groupedBarCenter(comboScales.band, comboScales.group, label, seriesKey)
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
                const perSeriesScales: BarScaleSet = {
                    band: comboScales.band,
                    value: resolveYScaleForSeries(comboScales, s),
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

            // ── 2. Area fills first, then lines + points. Two passes so every area sits
            //      below every line regardless of input order — a single per-series loop
            //      would paint a later area over an earlier line.
            withPlotClip(ctx, dimensions, () => {
                for (const s of lineSeries) {
                    const stype = seriesTypeOf(s)
                    if (stype !== 'area' && !s.fill) {
                        continue
                    }
                    drawArea(
                        { ...baseDrawCtx, yScale: resolveYScaleForSeries(comboScales, s) },
                        s,
                        undefined,
                        s.fill?.lowerData
                    )
                }
                for (const s of lineSeries) {
                    if (s.fill?.lowerData) {
                        continue
                    }
                    const drawCtx: DrawContext = { ...baseDrawCtx, yScale: resolveYScaleForSeries(comboScales, s) }
                    drawLine(drawCtx, s)
                    drawPoints(drawCtx, s)
                }
            })
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
            const { bars: barSeries, lines: lineSeries } = partitionByType(coloredSeries, seriesTypeOf)

            // Bars: only highlight those whose band-axis extent contains the cursor.
            let barHits: Set<string> | null = null
            if (hoverPosition) {
                barHits = barKeysAtCursor({
                    series: barSeries,
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

            for (const s of barSeries) {
                if (barHits && !barHits.has(s.key)) {
                    continue
                }
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const perSeriesScales: BarScaleSet = {
                    band: comboScales.band,
                    value: resolveYScaleForSeries(comboScales, s),
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
                const highlightColor = darkenedColors.get(s.key) ?? d3.color(s.color)?.darker(0.6).toString() ?? s.color
                drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
            }

            // Lines/areas — highlight ring at the band center for this index. Auxiliary
            // overlays (trendlines, moving averages) opt out — they should not surface as
            // primary points on hover. Mirrors LineChart.drawHover.
            const x = bandCenter(comboScales.band, hoveredLabel)
            if (x == null) {
                return
            }
            for (const s of lineSeries) {
                if (s.fill?.lowerData || s.overlay) {
                    continue
                }
                const raw = s.data[hoverIndex]
                if (raw == null || !isFinite(raw)) {
                    continue
                }
                const y = resolveYScaleForSeries(comboScales, s)(raw)
                if (isFinite(y)) {
                    drawHighlightPoint(ctx, x, y, s.color, theme.backgroundColor ?? '#ffffff')
                }
            }
        },
        [
            seriesTypeOf,
            barLayout,
            barStackedData,
            topStackedKeyByAxis,
            barCornerRadius,
            defaultSeriesType,
            darkenedColors,
        ]
    )

    // Bar segments report their own value; lines report raw. buildSegmentResolveValue's fallback
    // handles non-bar series automatically (they aren't in barStackedData), so we can pass the
    // bar-only stack and still get correct line values.
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
