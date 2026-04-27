import React, { useCallback, useMemo, useRef } from 'react'

import { drawArea, drawGrid, drawHighlightPoint, drawLine, drawPoints } from '../core/canvas-renderer'
import type { DrawContext } from '../core/canvas-renderer'
import { Chart } from '../core/Chart'
import { computePercentStackData, computeStackData, createScales as createLineScales } from '../core/scales'
import type { ScaleSet, StackedBand } from '../core/scales'
import { DEFAULT_Y_AXIS_ID } from '../core/types'
import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipContext,
    YAxisScale,
} from '../core/types'

export interface LineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: LineChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    children?: React.ReactNode
}

export function LineChart<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    children,
}: LineChartProps<Meta>): React.ReactElement {
    const { yScaleType = 'linear', percentStackView = false, showGrid = false } = config ?? {}

    const hasAreaFill = useMemo(() => series.some((s) => s.fillArea && !s.fillBetweenData), [series])

    const stackedData = useMemo((): Map<string, StackedBand> | undefined => {
        if (percentStackView) {
            return computePercentStackData(series, labels)
        }
        if (hasAreaFill) {
            return computeStackData(series, labels)
        }
        return undefined
    }, [percentStackView, hasAreaFill, series, labels])

    const chartConfig = useMemo(() => {
        if (!percentStackView || config?.yTickFormatter) {
            return config
        }
        return {
            ...config,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, percentStackView])

    // Keep a ref to the raw d3 scales so the draw callback can use them
    // without exposing d3 types through the ChartScales abstraction
    const d3ScalesRef = useRef<ScaleSet | null>(null)

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: Series[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            // When stacking (non-percent), use stacked top values so the y-domain
            // reflects the cumulative totals rather than individual series values
            let seriesForScale = coloredSeries
            if (stackedData && !percentStackView) {
                seriesForScale = coloredSeries.map((s) => {
                    const band = stackedData.get(s.key)
                    return band ? { ...s, data: band.top } : s
                })
            }
            const d3Scales = createLineScales(seriesForScale, scaleLabels, dimensions, {
                scaleType: yScaleType,
                percentStack: percentStackView,
            })
            d3ScalesRef.current = d3Scales

            let yAxes: Record<string, YAxisScale> | undefined
            if (d3Scales.yAxes) {
                yAxes = {}
                for (const [axisId, { scale, position }] of Object.entries(d3Scales.yAxes)) {
                    yAxes[axisId] = {
                        scale: (value: number) => scale(value),
                        ticks: () => scale.ticks?.() ?? [],
                        position,
                    }
                }
            }

            return {
                x: (label: string) => d3Scales.x(label),
                y: (value: number) => d3Scales.y(value),
                yTicks: () => d3Scales.y.ticks?.() ?? [],
                yAxes,
            }
        },
        [yScaleType, percentStackView, stackedData]
    )

    const draw = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs) => {
            const d3Scales = d3ScalesRef.current
            if (!d3Scales) {
                return
            }

            const resolveYScale = (s: Series): typeof d3Scales.y => {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                return d3Scales.yAxes?.[axisId]?.scale ?? d3Scales.y
            }

            const resolveChartYScale = (s: Series): ((value: number) => number) => {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                return scales.yAxes?.[axisId]?.scale ?? scales.y
            }

            const baseDrawCtx: DrawContext = {
                ctx,
                dimensions,
                xScale: d3Scales.x,
                yScale: d3Scales.y,
                labels: drawLabels,
            }

            if (showGrid) {
                drawGrid(baseDrawCtx, { gridColor: theme.gridColor })
            }

            for (const s of coloredSeries) {
                if (s.hidden) {
                    continue
                }

                const drawCtx: DrawContext = { ...baseDrawCtx, yScale: resolveYScale(s) }
                const band = stackedData?.get(s.key)
                const yValues = band?.top

                if (s.fillArea) {
                    drawArea(drawCtx, s, yValues, s.fillBetweenData ?? band?.bottom)
                }
                if (!s.fillBetweenData) {
                    drawLine(drawCtx, s, yValues)
                    drawPoints(drawCtx, s, yValues)
                }
            }

            if (hoverIndex >= 0) {
                for (const s of coloredSeries) {
                    if (s.hidden || s.fillBetweenData) {
                        continue
                    }
                    const data = stackedData?.get(s.key)?.top ?? s.data
                    const x = scales.x(drawLabels[hoverIndex])
                    const yScaleFn = resolveChartYScale(s)
                    const y = yScaleFn(data[hoverIndex])
                    if (x != null && isFinite(y)) {
                        drawHighlightPoint(ctx, x, y, s.color, theme.backgroundColor ?? '#ffffff')
                    }
                }
            }
        },
        [showGrid, stackedData]
    )

    const resolveValue = useMemo(() => {
        if (!stackedData) {
            return undefined
        }
        return (s: Series, dataIndex: number): number =>
            stackedData.get(s.key)?.top[dataIndex] ?? s.data[dataIndex] ?? 0
    }, [stackedData])

    return (
        <Chart
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            createScales={createScales}
            draw={draw}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            resolveValue={resolveValue}
        >
            {children}
        </Chart>
    )
}
