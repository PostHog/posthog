import React, { useCallback, useMemo, useRef } from 'react'

import {
    type BarRect,
    type BarRoundedCorners,
    drawBarHighlight,
    drawBars,
    drawGrid,
    type DrawContext,
} from '../core/canvas-renderer'
import { Chart } from '../core/Chart'
import { ChartErrorBoundary } from '../core/ChartErrorBoundary'
import {
    type BarScaleSet,
    computePercentStackData,
    computeStackData,
    createBarScales,
    yTickCountForHeight,
} from '../core/scales'
import type { StackedBand } from '../core/scales'
import type {
    BarChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    Series,
    TooltipContext,
} from '../core/types'

export interface BarChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: BarChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Bars laid out for a single series across all labels, indexed by data index. */
type SeriesBarLayout = (BarRect | null)[]

/** Pick which corners to round for a bar's cap. The cap is the side away from the
 *  value-axis baseline; for stacked layers below the topmost we don't round at all. */
function cornersFor(isHorizontal: boolean, isPositive: boolean, shouldRoundCap: boolean): BarRoundedCorners {
    if (!shouldRoundCap) {
        return {}
    }
    if (isHorizontal) {
        return isPositive ? { topRight: true, bottomRight: true } : { topLeft: true, bottomLeft: true }
    }
    return isPositive ? { topLeft: true, topRight: true } : { bottomLeft: true, bottomRight: true }
}

/** Computes bar geometry for one series given the layout mode and band scales.
 *  Returns one entry per data index (or null when the bar is not drawable). */
function computeSeriesBars(
    series: Series,
    labels: string[],
    scales: BarScaleSet,
    layout: 'stacked' | 'grouped' | 'percent',
    isHorizontal: boolean,
    stackedBand: StackedBand | undefined,
    isTopOfStack: boolean
): SeriesBarLayout {
    const result: SeriesBarLayout = []
    const bandWidth = scales.band.bandwidth()
    const valueAtZero = scales.value(0)

    for (let i = 0; i < labels.length; i++) {
        const bandStart = scales.band(labels[i])
        if (bandStart == null) {
            result.push(null)
            continue
        }

        const raw = series.data[i]
        if (raw == null || !isFinite(raw)) {
            result.push(null)
            continue
        }

        // Cap end is the side away from the value axis baseline — the only side that gets rounded.
        // Stacked bars only round the topmost segment; non-stacked bars always round their cap.
        const shouldRoundCap = layout === 'grouped' || isTopOfStack

        if (layout === 'grouped') {
            const groupOffset = scales.group?.(series.key)
            if (groupOffset == null) {
                result.push(null)
                continue
            }
            const groupBandWidth = scales.group?.bandwidth() ?? bandWidth
            const valuePixel = scales.value(raw)
            if (!isFinite(valuePixel)) {
                result.push(null)
                continue
            }

            const corners = cornersFor(isHorizontal, raw >= 0, shouldRoundCap)
            if (isHorizontal) {
                const x = Math.min(valueAtZero, valuePixel)
                const width = Math.abs(valuePixel - valueAtZero)
                result.push({
                    x,
                    y: bandStart + groupOffset,
                    width,
                    height: groupBandWidth,
                    corners,
                    dataIndex: i,
                })
            } else {
                const y = Math.min(valueAtZero, valuePixel)
                const height = Math.abs(valuePixel - valueAtZero)
                result.push({
                    x: bandStart + groupOffset,
                    y,
                    width: groupBandWidth,
                    height,
                    corners,
                    dataIndex: i,
                })
            }
            continue
        }

        // Stacked / percent: use the band's stacked top/bottom values.
        const top = stackedBand?.top[i] ?? raw
        const bottom = stackedBand?.bottom[i] ?? 0
        const topPixel = scales.value(top)
        const bottomPixel = scales.value(bottom)
        if (!isFinite(topPixel) || !isFinite(bottomPixel)) {
            result.push(null)
            continue
        }

        if (isHorizontal) {
            const x = Math.min(topPixel, bottomPixel)
            const width = Math.abs(topPixel - bottomPixel)
            result.push({
                x,
                y: bandStart,
                width,
                height: bandWidth,
                corners: shouldRoundCap ? { topRight: true, bottomRight: true } : {},
                dataIndex: i,
            })
        } else {
            const y = Math.min(topPixel, bottomPixel)
            const height = Math.abs(topPixel - bottomPixel)
            result.push({
                x: bandStart,
                y,
                width: bandWidth,
                height,
                corners: shouldRoundCap ? { topLeft: true, topRight: true } : {},
                dataIndex: i,
            })
        }
    }
    return result
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

    // Keep a ref to the raw d3 scales so the draw callback can use them
    // without exposing d3 types through the ChartScales abstraction
    const d3ScalesRef = useRef<BarScaleSet | null>(null)

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: Series[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
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
                x: (label: string) => {
                    const start = d3Scales.band(label)
                    if (start == null) {
                        return undefined
                    }
                    return start + d3Scales.band.bandwidth() / 2
                },
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
                xScale: (label: string) => {
                    const start = d3Scales.band(label)
                    return start == null ? undefined : start + d3Scales.band.bandwidth() / 2
                },
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
                const bars = computeSeriesBars(s, drawLabels, d3Scales, barLayout, isHorizontal, stackedBand, isTop)
                drawBars(
                    baseDrawCtx,
                    s,
                    bars.filter((b): b is BarRect => b !== null),
                    { cornerRadius: barCornerRadius }
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
                const bars = computeSeriesBars(s, drawLabels, d3Scales, barLayout, isHorizontal, stackedBand, isTop)
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
        // Return the stacked top so the tooltip anchor lands at the visual top of each bar segment,
        // not at the raw series value. This matches LineChart's behavior for stacked area charts —
        // consumers wanting raw per-series values in the tooltip should override the tooltip render
        // and look up `series.data[dataIndex]` themselves.
        return (s: Series, dataIndex: number): number => {
            const stacked = stackedData.get(s.key)?.top[dataIndex]
            if (stacked != null && Number.isFinite(stacked)) {
                return stacked
            }
            const raw = s.data[dataIndex]
            return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
        }
    }, [stackedData])

    // Pass band-center coordinates through to the interaction layer.
    // For horizontal layout, the interaction axis is y; otherwise x.
    const labelToCoord = useCallback((label: string): number | undefined => {
        const d3Scales = d3ScalesRef.current
        if (!d3Scales) {
            return undefined
        }
        const start = d3Scales.band(label)
        return start == null ? undefined : start + d3Scales.band.bandwidth() / 2
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
            resolveValue={resolveValue}
            interactionAxis={isHorizontal ? 'y' : 'x'}
            labelToCoord={isHorizontal ? labelToCoord : undefined}
        >
            {children}
        </Chart>
    )
}
