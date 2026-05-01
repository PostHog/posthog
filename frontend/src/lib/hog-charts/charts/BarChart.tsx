import React, { useCallback, useMemo, useRef } from 'react'

import { computeSeriesBars } from '../core/bar-layout'
import { type BarRect, drawBarHighlight, drawBars, drawGrid, type DrawContext } from '../core/canvas-renderer'
import { Chart } from '../core/Chart'
import { ChartErrorBoundary } from '../core/ChartErrorBoundary'
import {
    type BarScaleSet,
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

function bandCenter(scales: BarScaleSet, label: string): number | undefined {
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
        bandPadding = 0.2,
        groupPadding = 0.1,
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

    // Pick which series should round its cap in stacked/percent layouts.
    // d3.stack uses the order passed to `stack.keys()` (here: visible series in their array order),
    // so the topmost visual layer at every x is the last visible series. That key gets cap rounding.
    // If the consumer reorders or hides series, this recomputes — `series` and `excluded` flags
    // are both in the dep array.
    const topStackedKey = useMemo<string | null>(() => {
        if (barLayout === 'grouped') {
            return null
        }
        const visible = series.filter((s) => !s.visibility?.excluded)
        return visible.length > 0 ? visible[visible.length - 1].key : null
    }, [barLayout, series])

    const chartConfig = useMemo<BarChartConfig | undefined>(() => {
        if (barLayout !== 'percent' || config?.yTickFormatter) {
            return config
        }
        return {
            ...config,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, barLayout])

    const d3ScalesRef = useRef<BarScaleSet | null>(null)

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
                bandPadding,
                groupPadding,
                stackedSeries,
            })
            d3ScalesRef.current = d3Scales

            const tickAxisLength = isHorizontal ? dimensions.plotWidth : dimensions.plotHeight
            const yTickCount = yTickCountForHeight(tickAxisLength)

            // For horizontal, expose the value scale as `y` (since AxisLabels horizontal mode
            // calls `scales.y(tick)` for x-pixel positioning of value ticks).
            // For vertical, `y` is the value scale on the y-axis.
            return {
                x: (label: string) => bandCenter(d3Scales, label),
                y: (value: number) => d3Scales.value(value),
                yTicks: () => d3Scales.value.ticks?.(yTickCount) ?? [],
            }
        },
        [yScaleType, barLayout, axisOrientation, bandPadding, groupPadding, stackedData, isHorizontal]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
            const d3Scales = d3ScalesRef.current
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
                const isTop = topStackedKey !== null && s.key === topStackedKey
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
        [showGrid, stackedData, barLayout, isHorizontal, topStackedKey, barCornerRadius]
    )

    const drawHover = useCallback(
        ({ ctx, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs) => {
            const d3Scales = d3ScalesRef.current
            if (!d3Scales || hoverIndex < 0) {
                return
            }
            const highlightColor = theme.crosshairColor ?? 'rgba(0, 0, 0, 0.4)'
            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const stackedBand = stackedData?.get(s.key)
                const isTop = topStackedKey !== null && s.key === topStackedKey
                const bars = computeSeriesBars({
                    series: s,
                    labels: drawLabels,
                    scales: d3Scales,
                    layout: barLayout,
                    isHorizontal,
                    stackedBand,
                    isTopOfStack: isTop,
                })
                const bar = bars[hoverIndex]
                if (bar) {
                    drawBarHighlight(ctx, bar, highlightColor, barCornerRadius)
                }
            }
        },
        [stackedData, barLayout, isHorizontal, topStackedKey, barCornerRadius]
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

    const labelToCoord = useCallback((label: string): number | undefined => {
        const d3Scales = d3ScalesRef.current
        return d3Scales ? bandCenter(d3Scales, label) : undefined
    }, [])

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
            labelToCoord={isHorizontal ? labelToCoord : undefined}
        >
            {children}
        </Chart>
    )
}
