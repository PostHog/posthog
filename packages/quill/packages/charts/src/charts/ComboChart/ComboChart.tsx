import { color as d3Color } from 'd3-color'
import React, { useCallback, useMemo } from 'react'

import { bandCenter, buildBarLayers, computeBarAtIndex, groupedBarCenter } from '../../core/bar-layout'
import {
    BAR_HIGHLIGHT_DARKEN,
    DEFAULT_BAR_CORNER_RADIUS,
    LINE_STROKE_WIDTH,
    drawAxes,
    resolveAxisLineColor,
    drawBarHighlight,
    drawBars,
    drawGrid,
    drawLineHoverPoints,
    drawLineSeriesLayer,
    type DrawContext,
} from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { barColorAt } from '../../core/color-utils'
import { type ComboChartPrivate, createComboScales, partitionByType, resolveSeriesType } from '../../core/combo-scales'
import {
    buildSegmentResolveValue,
    buildStackedBottomValue,
    buildStackedPositionValue,
    computePercentStackData,
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
        showAxisLines = false,
        barLayout = 'stacked',
        barCornerRadius = DEFAULT_BAR_CORNER_RADIUS,
        defaultSeriesType = DEFAULT_SERIES_TYPE,
        xTickFormatter,
        valueDomain,
        curve,
    } = config ?? {}
    const smooth = curve === 'monotone'

    const seriesTypeOf = useCallback(
        (s: Pick<Series, 'type'>): SeriesType => resolveSeriesType(s, defaultSeriesType),
        [defaultSeriesType]
    )

    // Stack only bar series together. Lines/areas are explicitly excluded so a line doesn't get a
    // bottom-of-stack offset and bars don't widen the line's drawn baseline.
    const barStackedData = useMemo<Map<string, StackedBand> | undefined>(() => {
        if (barLayout !== 'stacked' && barLayout !== 'percent') {
            return undefined
        }
        const barSeries = series.filter((s) => seriesTypeOf(s) === 'bar')
        if (barSeries.length === 0) {
            return undefined
        }
        return barLayout === 'percent'
            ? computePercentStackData(barSeries, labels)
            : computeStackData(barSeries, labels)
    }, [barLayout, series, labels, seriesTypeOf])

    // Per-axis topmost bar — only bar layers below the cap forgo corner rounding. Non-bar series are
    // skipped so lines/areas don't take part in bar stacking. Shares BarChart's helper.
    const topStackedKeyByAxis = useMemo<Map<string, string>>(
        () =>
            barLayout !== 'stacked' && barLayout !== 'percent'
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
                valueDomain,
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
        [yScaleType, barLayout, seriesTypeOf, barStackedData, valueDomain]
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

            // Grid sits behind the data; the L-axis is drawn after the series (below) so neither bars
            // nor lines paint over the baseline where they meet the axis.
            if (showGrid) {
                // In the axis-line style only the value-axis grid guides reading; category lines
                // through the band gaps are noise (line charts never draw them either).
                const categoryTicks = showAxisLines
                    ? []
                    : computeVisibleXLabels(drawLabels, (label) => bandCenter(comboScales, label), xTickFormatter).map(
                          (entry) => entry.x
                      )
                drawGrid(baseDrawCtx, {
                    gridColor: theme.gridColor,
                    gridDash: theme.gridDashPattern,
                    frame: !showAxisLines,
                    categoryTicks,
                })
            }

            // ── 1. Bars ──────────────────────────────────────────────────────────────────────
            // `comboScales` is structurally a `BarScaleSet`; `buildBarLayers` (shared with BarChart)
            // resolves each series' own axis (`yAxes[id] ?? value`), so dual-axis bars draw correctly.
            const barLayers = buildBarLayers({
                series: barSeries,
                labels: drawLabels,
                scales: comboScales,
                layout: barLayout,
                isHorizontal: false,
                stackedData: barStackedData,
                topStackedKeyByAxis,
            })
            for (const { series: s, bars } of barLayers) {
                drawBars(baseDrawCtx, s, bars, barCornerRadius)
            }

            // ── 2. Lines + areas (shared with LineChart). `areas-first` so every area sits below
            //      every line regardless of input order; combo lines aren't stacked, so the raw data
            //      is used and a series counts as filled when its type is 'area' or it sets `fill`.
            drawLineSeriesLayer({
                ctx,
                dimensions,
                labels: drawLabels,
                series: lineSeries,
                xScale: (label) => bandCenter(comboScales, label),
                resolveYScale: (s) => resolveYScaleForSeries(comboScales, s),
                shouldFill: (s) => seriesTypeOf(s) === 'area' || !!s.fill,
                bottomFor: (s) => s.fill?.lowerData,
                zOrder: 'areas-first',
                smooth,
                // Rest baseline-hugging strokes on the axis line, and trim the first point's
                // stroke at the y-axis, instead of straddling either axis line.
                yFloor: showAxisLines
                    ? dimensions.plotTop + dimensions.plotHeight - LINE_STROKE_WIDTH / 2
                    : undefined,
                clipLeftEdge: showAxisLines,
            })

            if (showAxisLines) {
                drawAxes(baseDrawCtx, { axisColor: resolveAxisLineColor(theme) })
            }
        },
        [
            seriesTypeOf,
            showGrid,
            showAxisLines,
            xTickFormatter,
            barLayout,
            barStackedData,
            topStackedKeyByAxis,
            barCornerRadius,
            smooth,
        ]
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
    const resolveBottomValue = useMemo(() => buildStackedBottomValue(barStackedData), [barStackedData])

    // Mirrors BarChart: flag the axis context as percent (drives ValueLabels' 0-1 fraction
    // handling) and default the y-tick formatter to a percentage unless the caller overrides it.
    const chartConfig = useMemo<ComboChartConfig>(() => {
        const base = { ...config, isPercent: barLayout === 'percent' }
        if (barLayout !== 'percent' || config?.yTickFormatter) {
            return base
        }
        return {
            ...base,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, barLayout])

    return (
        <Chart
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
            resolveValue={resolveValue}
            resolvePositionValue={resolvePositionValue}
            resolveBottomValue={resolveBottomValue}
        >
            {children}
        </Chart>
    )
}
