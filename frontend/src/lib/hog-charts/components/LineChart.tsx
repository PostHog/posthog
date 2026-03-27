import React, { useCallback, useMemo } from 'react'

import { drawArea, drawGrid, drawHighlightPoint, drawLine, drawPoints } from '../core/canvas-renderer'
import type { DrawContext } from '../core/canvas-renderer'
import { Chart } from '../core/Chart'
import { computePercentStackData, createScales as createLineScales } from '../core/scales'
import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    CreateScalesFn,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipContext,
} from '../core/types'

export interface LineChartProps {
    series: Series[]
    labels: string[]
    config?: LineChartConfig
    tooltip?: React.ComponentType<TooltipContext>
    onPointClick?: (data: PointClickData) => void
    className?: string
    children?: React.ReactNode
}

export function LineChart({
    series,
    labels,
    config,
    tooltip,
    onPointClick,
    className,
    children,
}: LineChartProps): React.ReactElement {
    const { yScaleType = 'linear', percentStackView = false, showGrid = false, goalLines } = config ?? {}

    const stackedData = useMemo(() => {
        if (!percentStackView) {
            return undefined
        }
        return computePercentStackData(series, labels)
    }, [percentStackView, series, labels])

    const chartConfig = useMemo(() => {
        if (!percentStackView || config?.yTickFormatter) {
            return config
        }
        return {
            ...config,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, percentStackView])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: Series[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const scales = createLineScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                percentStack: percentStackView,
            })
            return {
                x: (label: string) => scales.x(label),
                y: (value: number) => scales.y(value),
                yRaw: scales.y,
            }
        },
        [yScaleType, percentStackView]
    )

    const draw = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs) => {
            const drawCtx: DrawContext = {
                ctx,
                dimensions,
                xScale: scales.x as unknown as d3.ScalePoint<string>,
                yScale: scales.yRaw,
                labels: drawLabels,
            }

            if (showGrid) {
                drawGrid(drawCtx, {
                    gridColor: theme.gridColor,
                    goalLineValues: goalLines?.map((g) => g.value),
                })
            }

            for (const s of coloredSeries) {
                if (s.hidden) {
                    continue
                }

                const yValues = stackedData?.get(s.key)

                if (s.fillArea) {
                    drawArea(drawCtx, s, yValues)
                }
                drawLine(drawCtx, s, yValues)
                drawPoints(drawCtx, s, yValues)
            }

            if (hoverIndex >= 0) {
                for (const s of coloredSeries) {
                    if (s.hidden) {
                        continue
                    }
                    const data = stackedData?.get(s.key) ?? s.data
                    const x = scales.x(drawLabels[hoverIndex])
                    const y = scales.y(data[hoverIndex])
                    if (x != null && isFinite(y)) {
                        drawHighlightPoint(ctx, x, y, s.color)
                    }
                }
            }
        },
        [showGrid, goalLines, stackedData]
    )

    return (
        <Chart
            series={series}
            labels={labels}
            config={chartConfig}
            createScales={createScales}
            draw={draw}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            stackedData={stackedData}
        >
            {children}
        </Chart>
    )
}
