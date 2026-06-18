import { color as d3Color } from 'd3-color'
import React, { useCallback, useMemo } from 'react'

import { bandCenter, computeBarAtIndex, computeSeriesBars, groupedBarCenter } from '../../core/bar-layout'
import {
    BAR_HIGHLIGHT_DARKEN,
    type BarRect,
    DEFAULT_BAR_CORNER_RADIUS,
    drawArea,
    drawBarHighlight,
    drawBars,
    drawGrid,
    drawLine,
    drawLineHoverPoints,
    drawPoints,
    type DrawContext,
    withVerticalClip,
} from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { barColorAt } from '../../core/color-utils'
import { type ComboChartPrivate, createComboScales, partitionByType, resolveSeriesType } from '../../core/combo-scales'
import {
    buildSegmentResolveValue,
    buildStackedPositionValue,
    computeStackData,
    computeTopStackedKeyByAxis,
    resolveYScaleForSeries,
    type StackedBand,
    toYAxisScales,
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
} from '../../core/types'
import { DEFAULT_SERIES_TYPE, DEFAULT_Y_AXIS_ID } from '../../core/types'
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
        defaultSeriesType = DEFAULT_SERIES_TYPE,
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

    // Per-axis topmost bar — only bar layers below the cap forgo corner rounding. Non-bar series are
    // skipped so lines/areas don't take part in bar stacking. Shares BarChart's helper.
    const topStackedKeyByAxis = useMemo<Map<string, string>>(
        () =>
            barLayout !== 'stacked'
                ? new Map()
                : computeTopStackedKeyByAxis(series, { skip: (s) => seriesTypeOf(s) !== 'bar' }),
        [barLayout, series, seriesTypeOf]
    )

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const comboScales = createComboScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                barLayout,
                seriesTypeOf,
                barStackedData,
            })

            const yTickCount = yTickCountForHeight(dimensions.plotHeight)

            // Pre-index series by key so the grouped `x` closure resolves seriesKey → type in O(1)
            // instead of scanning the array on every overlay/value-label call.
            const seriesByKey = new Map<string, ResolvedSeries>()
            for (const s of coloredSeries) {
                seriesByKey.set(s.key, s)
            }

            const comboPrivate: ComboChartPrivate = { __comboChart: comboScales }

            return {
                x: (label: string, seriesKey?: string) => {
                    // Only grouped bars get a per-series sub-band offset; everything else (lines,
                    // areas, the unkeyed call) anchors at the band center.
                    if (seriesKey == null || barLayout !== 'grouped') {
                        return bandCenter(comboScales, label)
                    }
                    const s = seriesByKey.get(seriesKey)
                    if (s && seriesTypeOf(s) === 'bar') {
                        return groupedBarCenter(comboScales, label, seriesKey) ?? bandCenter(comboScales, label)
                    }
                    return bandCenter(comboScales, label)
                },
                y: (v: number) => comboScales.y(v),
                yTicks: () => comboScales.y.ticks?.(yTickCount) ?? [],
                yAxes: toYAxisScales(comboScales.yAxes, yTickCount),
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

            // ── 1. Bars ──────────────────────────────────────────────────────────────────────
            // `comboScales` is structurally a `BarScaleSet`; `computeSeriesBars` resolves each
            // series' own axis (`yAxes[id] ?? value`), so dual-axis bars draw against the right scale.
            for (const s of barSeries) {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const bars = computeSeriesBars({
                    series: s,
                    labels: drawLabels,
                    scales: comboScales,
                    layout: barLayout,
                    isHorizontal: false,
                    stackedBand: barStackedData?.get(s.key),
                    isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
                }).filter((b): b is BarRect => b !== null)
                drawBars(baseDrawCtx, s, bars, barCornerRadius)
            }

            // ── 2. Area fills first, then lines + points. Two passes so every area sits below every
            //      line regardless of input order — a single per-series loop would paint a later
            //      area over an earlier line. Clipped vertically (shared with LineChart).
            withVerticalClip(ctx, dimensions, () => {
                for (const s of lineSeries) {
                    if (seriesTypeOf(s) !== 'area' && !s.fill) {
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

            // Bars: only highlight those whose band-axis extent contains the cursor. The shared bar
            // resolver works directly on the combo scales (per-axis resolution inside computeBarAtIndex).
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
                const bar = computeBarAtIndex({
                    series: s,
                    label: hoveredLabel,
                    dataIndex: hoverIndex,
                    scales: comboScales,
                    layout: barLayout,
                    isHorizontal: false,
                    stackedBand: barStackedData?.get(s.key),
                    isTopOfStack: topStackedKeyByAxis.get(axisId) === s.key,
                })
                if (!bar) {
                    continue
                }
                const barColor = barColorAt(s, bar.dataIndex)
                const highlightColor = d3Color(barColor)?.darker(BAR_HIGHLIGHT_DARKEN).toString() ?? barColor
                drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
                drewAny = true
            }

            // Lines/areas — highlight ring at the band center for this index (shared with LineChart).
            const x = bandCenter(comboScales, hoveredLabel)
            if (x != null) {
                const drewLine = drawLineHoverPoints(ctx, lineSeries, theme.backgroundColor ?? '#ffffff', (s) => {
                    const raw = s.data[hoverIndex]
                    if (raw == null || !isFinite(raw)) {
                        return null
                    }
                    return { x, y: resolveYScaleForSeries(comboScales, s)(raw) }
                })
                drewAny = drewAny || drewLine
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
