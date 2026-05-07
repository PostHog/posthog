import React, { useCallback, useMemo } from 'react'

import { drawArea, drawGrid, drawHighlightPoint, drawLine, drawPoints } from '../core/canvas-renderer'
import type { DrawContext } from '../core/canvas-renderer'
import { Chart } from '../core/Chart'
import { ChartErrorBoundary } from '../core/ChartErrorBoundary'
import {
    computePercentStackData,
    computeStackData,
    createScales as createLineScales,
    yTickCountForHeight,
} from '../core/scales'
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
    ResolvedSeries,
    Series,
    TooltipContext,
    YAxisScale,
} from '../core/types'

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
    const { yScaleType = 'linear', percentStackView = false, showGrid = false } = config ?? {}

    const hasAreaFill = useMemo(() => series.some((s) => s.fill !== undefined && !s.fill.lowerData), [series])

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
            })

            const yTickCount = yTickCountForHeight(dimensions.plotHeight)

            let yAxes: Record<string, YAxisScale> | undefined
            if (d3Scales.yAxes) {
                yAxes = {}
                for (const [axisId, { scale, position }] of Object.entries(d3Scales.yAxes)) {
                    yAxes[axisId] = {
                        scale: (value: number) => scale(value),
                        ticks: () => scale.ticks?.(yTickCount) ?? [],
                        position,
                    }
                }
            }

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
        [yScaleType, percentStackView, stackedData]
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
            }

            // Clip data drawing to the plot area so an overlay series with values outside
            // the y-domain (e.g. a trendline projecting below 0) doesn't bleed into the
            // axis-label gutter beneath the chart. A small pad on top/bottom keeps strokes
            // at the domain edge from rendering at half-thickness — line strokes and point
            // markers extend past the value's pixel center.
            const CLIP_PAD = 8
            ctx.save()
            ctx.beginPath()
            ctx.rect(
                dimensions.plotLeft,
                dimensions.plotTop - CLIP_PAD,
                dimensions.plotWidth,
                dimensions.plotHeight + CLIP_PAD * 2
            )
            ctx.clip()

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

            ctx.restore()
        },
        [showGrid, stackedData]
    )

    const drawHover = useCallback(
        ({ ctx, scales, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs) => {
            if (hoverIndex < 0) {
                return
            }
            const resolveChartYScale = (s: ResolvedSeries): ((value: number) => number) => {
                const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
                return scales.yAxes?.[axisId]?.scale ?? scales.y
            }
            for (const s of coloredSeries) {
                if (s.visibility?.excluded || s.fill?.lowerData) {
                    continue
                }
                // Auxiliary overlays (moving averages, trend lines) opt out of stacking.
                // In percent-stack mode the y-scale domain is [0, 1], so mapping their raw
                // values produces a highlight ring far outside the plot — skip them entirely.
                if (s.overlay) {
                    continue
                }
                const data = stackedData?.get(s.key)?.top ?? s.data
                const x = scales.x(drawLabels[hoverIndex])
                const y = resolveChartYScale(s)(data[hoverIndex])
                if (x != null && isFinite(y)) {
                    drawHighlightPoint(ctx, x, y, s.color, theme.backgroundColor ?? '#ffffff')
                }
            }
        },
        [stackedData]
    )

    const resolveValue = useMemo(() => {
        if (!stackedData) {
            return undefined
        }
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
