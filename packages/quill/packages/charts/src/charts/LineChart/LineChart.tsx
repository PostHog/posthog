import React, { useCallback, useMemo } from 'react'

import { drawArea, drawAxes, drawGrid, drawLine, drawLineHoverPoints, drawPoints } from '../../core/canvas-renderer'
import type { DrawContext } from '../../core/canvas-renderer'
import { withVerticalClip } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import {
    buildSegmentResolveValue,
    buildStackedPositionValue,
    computePercentStackData,
    computeStackData,
    createScales as createLineScales,
    resolveYScaleForSeries,
    toYAxisScales,
    yTickCountForHeight,
} from '../../core/scales'
import type { ScaleSet, StackedBand } from '../../core/scales'
import { DEFAULT_Y_AXIS_ID } from '../../core/types'
import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    LineChartConfig,
    PointClickData,
    ResolvedSeries,
    Series,
    TooltipContext,
} from '../../core/types'

// Brand for the private ChartScales._private slot used by LineChart. The base Chart
// and other chart types treat this as opaque; LineChart's drawStatic narrows back to it.
interface LineChartPrivate {
    __lineChart: ScaleSet
}

export interface LineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: LineChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function LineChart<Meta = unknown>({ onError, ...rest }: LineChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <LineChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function LineChartInner<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    dataAttr,
    children,
}: LineChartProps<Meta>): React.ReactElement {
    const {
        yScaleType = 'linear',
        percentStackView = false,
        showGrid = false,
        showAxisLines = false,
        valueDomain,
    } = config ?? {}

    const hasMultipleFilledSeries = useMemo(() => {
        const filledSeries = series.filter((s) => s.fill && !s.fill.lowerData)
        return filledSeries.length >= 2
    }, [series])

    const stackedData = useMemo((): Map<string, StackedBand> | undefined => {
        if (percentStackView) {
            return computePercentStackData(series, labels)
        }
        // Only stack when there are 2+ fillable series — a single area series has nothing to stack
        // against, and forcing a stacked band would feed a `bottomValues` array into the canvas
        // renderer, which disables the gradient fill path.
        if (hasMultipleFilledSeries) {
            return computeStackData(series, labels)
        }
        return undefined
    }, [percentStackView, hasMultipleFilledSeries, series, labels])

    const chartConfig = useMemo(() => {
        const base = { ...config, isPercent: percentStackView }
        if (!percentStackView || config?.yTickFormatter) {
            return base
        }
        return {
            ...base,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, percentStackView])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
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
                valueDomain,
            })

            const yTickCount = yTickCountForHeight(dimensions.plotHeight)

            const yAxes = d3Scales.yAxes ? toYAxisScales(d3Scales.yAxes, yTickCount) : undefined

            // Stash raw d3 scales in the private slot so drawStatic can read them without
            // a side-channel ref — every render gets a self-contained ChartScales object,
            // which avoids strict-mode / concurrent-rendering races between the createScales
            // pass and the static-draw effect.
            const lineChartPrivate: LineChartPrivate = { __lineChart: d3Scales }

            return {
                x: (label: string) => d3Scales.x(label),
                y: (value: number) => d3Scales.y(value),
                yTicks: () => d3Scales.y.ticks?.(yTickCount) ?? [],
                yAxes,
                _private: lineChartPrivate,
            }
        },
        [yScaleType, percentStackView, stackedData, valueDomain]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
            const d3Scales = (scales._private as LineChartPrivate | undefined)?.__lineChart
            if (!d3Scales) {
                return
            }

            const resolveYScale = (s: ResolvedSeries): typeof d3Scales.y => {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                return d3Scales.yAxes?.[axisId]?.scale ?? d3Scales.y
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
            } else if (showAxisLines) {
                drawAxes(baseDrawCtx, { axisColor: theme.gridColor })
            }

            // Clip vertically only: keep out-of-domain values (e.g. a trendline below 0) out of the
            // axis-label gutters, but span the full width so edge point markers/line caps render whole.
            withVerticalClip(ctx, dimensions, () => {
                for (const s of coloredSeries) {
                    if (s.visibility?.excluded) {
                        continue
                    }

                    const drawCtx: DrawContext = { ...baseDrawCtx, yScale: resolveYScale(s) }
                    const band = stackedData?.get(s.key)
                    const yValues = band?.top

                    if (s.fill) {
                        drawArea(drawCtx, s, yValues, s.fill.lowerData ?? band?.bottom)
                    }
                    if (!s.fill?.lowerData) {
                        drawLine(drawCtx, s, yValues)
                        drawPoints(drawCtx, s, yValues)
                    }
                }
            })
        },
        [showGrid, showAxisLines, stackedData]
    )

    const drawHover = useCallback(
        ({ ctx, scales, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs): boolean => {
            if (hoverIndex < 0) {
                return false
            }
            // Overlays (moving averages, trend lines) and fill-between lower bounds opt out — in
            // percent-stack mode the y-domain is [0, 1], so their raw values would ring far off-plot.
            // `drawLineHoverPoints` handles those skips; we supply the stacked-top y per series.
            return drawLineHoverPoints(ctx, coloredSeries, theme.backgroundColor ?? '#ffffff', (s) => {
                const data = stackedData?.get(s.key)?.top ?? s.data
                const x = scales.x(drawLabels[hoverIndex])
                if (x == null) {
                    return null
                }
                return { x, y: resolveYScaleForSeries(scales, s)(data[hoverIndex]) }
            })
        },
        [stackedData]
    )

    // Stacked/percent-stacked areas: display each series's own segment value (resolveValue)
    // but anchor the tooltip/value labels at the stacked top (resolvePositionValue).
    const resolveValue = useMemo(() => buildSegmentResolveValue(stackedData), [stackedData])
    const resolvePositionValue = useMemo(() => buildStackedPositionValue(stackedData), [stackedData])

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
        >
            {children}
        </Chart>
    )
}
