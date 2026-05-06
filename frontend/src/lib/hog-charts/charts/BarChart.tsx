import React, { useCallback, useMemo } from 'react'

import { type BarChartPrivate, computeBarAtIndex, computeSeriesBars } from '../core/bar-layout'
import { type BarRect, drawBarHighlight, drawBars, drawGrid, type DrawContext } from '../core/canvas-renderer'
import { Chart } from '../core/Chart'
import { ChartErrorBoundary } from '../core/ChartErrorBoundary'
import {
    computePercentStackData,
    computeStackData,
    createBarScales,
    type StackedBand,
    yTickCountForHeight,
} from '../core/scales'
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
} from '../core/types'
import { DEFAULT_Y_AXIS_ID } from '../core/types'

function bandCenter(scales: BarChartPrivate['__barChart'], label: string): number | undefined {
    const start = scales.band(label)
    return start == null ? undefined : start + scales.band.bandwidth() / 2
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
        barCornerRadius = 4,
        axisOrientation = 'vertical',
    } = config ?? {}
    const isHorizontal = axisOrientation === 'horizontal'

    const stackedData = useMemo((): Map<string, StackedBand> | undefined => {
        if (barLayout === 'percent') {
            return computePercentStackData(series, labels)
        }
        if (barLayout === 'stacked') {
            return computeStackData(series, labels)
        }
        return undefined
    }, [barLayout, series, labels])

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
            let stackedSeries: Series[] | undefined
            if (stackedData && barLayout === 'stacked') {
                stackedSeries = coloredSeries.map((s) => {
                    const band = stackedData.get(s.key)
                    return band ? { ...s, data: band.top } : s
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
                x: (label: string) => bandCenter(d3Scales, label),
                y: (value: number) => d3Scales.value(value),
                yTicks: () => d3Scales.value.ticks?.(yTickCount) ?? [],
                _private: barChartPrivate,
            }
        },
        [yScaleType, barLayout, axisOrientation, stackedData, isHorizontal]
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
                drawGrid(baseDrawCtx, {
                    gridColor: theme.gridColor,
                    orientation: isHorizontal ? 'horizontal' : 'vertical',
                })
            }

            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const stackedBand = stackedData?.get(s.key)
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                const isTop = topStackedKeyByAxis.get(axisId) === s.key
                const bars = computeSeriesBars({
                    series: s,
                    labels: drawLabels,
                    scales: d3Scales,
                    layout: barLayout,
                    isHorizontal,
                    stackedBand,
                    isTopOfStack: isTop,
                })
                drawBars(
                    baseDrawCtx,
                    s,
                    bars.filter((b): b is BarRect => b !== null),
                    barCornerRadius
                )
            }
        },
        [showGrid, stackedData, barLayout, isHorizontal, topStackedKeyByAxis, barCornerRadius]
    )

    const drawHover = useCallback(
        ({ ctx, scales, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs) => {
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales || hoverIndex < 0) {
                return
            }
            const highlightColor = theme.crosshairColor ?? 'rgba(0, 0, 0, 0.4)'
            const hoveredLabel = drawLabels[hoverIndex]
            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
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
                if (bar) {
                    drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
                }
            }
        },
        [stackedData, barLayout, isHorizontal, topStackedKeyByAxis, barCornerRadius]
    )

    const resolveValue = useMemo(() => {
        if (!stackedData) {
            return undefined
        }
        // Return the stacked top so the tooltip anchor lands at the visual top of each segment, not the raw series value.
        return (s: Series, dataIndex: number): number => {
            const stacked = stackedData.get(s.key)?.top[dataIndex]
            if (stacked != null && Number.isFinite(stacked)) {
                return stacked
            }
            const raw = s.data[dataIndex]
            return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
        }
    }, [stackedData])

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
        >
            {children}
        </Chart>
    )
}
