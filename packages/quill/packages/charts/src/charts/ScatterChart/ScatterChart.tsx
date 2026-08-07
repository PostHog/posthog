import { scaleLinear, scaleLog, type ScaleLinear, type ScaleLogarithmic } from 'd3-scale'
import React, { useCallback, useMemo } from 'react'

import { drawHighlightPoint, drawPoints, resolveAxisLineColor } from '../../core/canvas-renderer'
import type { DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type {
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    ResolvedSeries,
    Series,
} from '../../core/types'
import { ScatterTooltip } from './ScatterTooltip'

// Matches DrawContext.yScale so a scale built here can drive the shared point/line draw helpers.
type NumericScale = ScaleLinear<number, number> | ScaleLogarithmic<number, number>

const DEFAULT_POINT_RADIUS = 4
const AXIS_FONT_SIZE = 11
const X_TICK_LABEL_GAP = 6
// Minimum horizontal gap between adjacent x-tick labels; dense log-scale ticks otherwise overlap.
const X_TICK_MIN_GAP = 8
const X_TITLE_GAP = 6
// Reserve enough bottom room for the canvas-drawn x-axis ticks (and title when present),
// since `hideXAxis` tells the base chart not to leave space for x labels of its own.
const X_AXIS_MARGIN = AXIS_FONT_SIZE + X_TICK_LABEL_GAP + 8
const X_TITLE_MARGIN = AXIS_FONT_SIZE + X_TITLE_GAP

// Brand for the private ChartScales._private slot ScatterChart populates. Opaque to the base
// Chart and overlays; drawStatic/drawHover narrow back to it to reach the raw d3 scales.
interface ScatterChartPrivate {
    __scatterChart: { xScale: NumericScale; yScale: NumericScale }
}

export interface ScatterChartPoint<Meta = unknown> {
    x: number
    y: number
    /** Tooltip title. Omit for a point with no label. */
    label?: string | null
    /** Overrides the tooltip's x readout — e.g. exact Int64 digits that `Number()` would round.
     *  Falls back to the formatted x value. */
    xDisplay?: string
    /** Overrides the tooltip's y readout. Falls back to the formatted y value. */
    yDisplay?: string
    /** Arbitrary consumer data, passed through to a custom `tooltip`. */
    meta?: Meta
}

export interface ScatterChartConfig {
    /** Plot the x-axis on a logarithmic scale. Points must be strictly positive. */
    xLogScale?: boolean
    /** Plot the y-axis on a logarithmic scale. Points must be strictly positive. */
    yLogScale?: boolean
    xAxisLabel?: string
    yAxisLabel?: string
    /** Point radius in CSS pixels. Defaults to 4. */
    pointRadius?: number
    /** Point color. Defaults to the first palette color from the theme. */
    color?: string
    /** Draw grid lines at the axis ticks. Defaults to true. */
    showGrid?: boolean
    /** Format an x-axis tick value. Defaults to a locale number. */
    xTickFormatter?: (value: number) => string
    /** Format a y-axis tick value. Defaults to the chart's auto-precision formatter. */
    yTickFormatter?: (value: number) => string
}

export interface ScatterChartProps<Meta = unknown> {
    points: ScatterChartPoint<Meta>[]
    theme: ChartTheme
    config?: ScatterChartConfig
    /** Custom tooltip for the hovered point. Defaults to a title + x/y readout. */
    tooltip?: (point: ScatterChartPoint<Meta>) => React.ReactNode
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const SERIES_KEY = 'scatter'

function defaultNumberFormat(value: number): string {
    return value.toLocaleString()
}

function computeDomain(logScale: boolean, values: number[]): [number, number] {
    if (values.length === 0) {
        return logScale ? [1, 10] : [0, 1]
    }
    let min = Math.min(...values)
    let max = Math.max(...values)
    if (min === max) {
        // A single distinct value would collapse the axis — pad it so the point sits mid-plot.
        const pad = min === 0 ? 1 : Math.abs(min) * 0.5
        min -= pad
        max += pad
    }
    // A log scale can't span zero/negatives; the caller filters those out, but clamp defensively.
    if (logScale && min <= 0) {
        min = Math.min(max, 1)
    }
    return [min, max]
}

function buildNumericScale(logScale: boolean, values: number[], range: [number, number]): NumericScale {
    const domain = computeDomain(logScale, values)
    // Build each branch on its concrete type so d3's overloaded methods resolve cleanly.
    return logScale ? scaleLog().domain(domain).range(range).nice() : scaleLinear().domain(domain).range(range).nice()
}

export function ScatterChart<Meta = unknown>({ onError, ...rest }: ScatterChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <ScatterChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function ScatterChartInner<Meta = unknown>({
    points,
    theme,
    config,
    tooltip,
    className,
    dataAttr,
}: ScatterChartProps<Meta>): React.ReactElement {
    const {
        xLogScale = false,
        yLogScale = false,
        xAxisLabel,
        yAxisLabel,
        pointRadius = DEFAULT_POINT_RADIUS,
        color,
        showGrid = true,
        xTickFormatter = defaultNumberFormat,
        yTickFormatter,
    } = config ?? {}

    // The hover hit-test binary-searches points by x pixel, which assumes ascending x — so sort once
    // and use the sorted order for labels, data, and tooltip lookup alike.
    const sortedPoints = useMemo(() => [...points].sort((a, b) => a.x - b.x), [points])

    const labels = useMemo(() => sortedPoints.map((_, i) => String(i)), [sortedPoints])

    const series = useMemo<Series[]>(
        () =>
            sortedPoints.length === 0
                ? []
                : [
                      {
                          key: SERIES_KEY,
                          label: yAxisLabel ?? '',
                          data: sortedPoints.map((point) => point.y),
                          color,
                          points: { radius: pointRadius },
                      },
                  ],
        [sortedPoints, yAxisLabel, color, pointRadius]
    )

    const margins = useMemo<Partial<ChartMargins>>(
        () => ({ bottom: X_AXIS_MARGIN + (xAxisLabel ? X_TITLE_MARGIN : 0) }),
        [xAxisLabel]
    )

    const chartConfig = useMemo<ChartConfig>(
        () => ({
            // The x-axis is continuous, so the base chart's categorical x-labels are hidden and drawn
            // by drawStatic instead. The y-axis stays on the base chart's numeric axis machinery.
            hideXAxis: true,
            yScaleType: yLogScale ? 'log' : 'linear',
            yAxisLabel,
            yTickFormatter,
            margins,
        }),
        [yLogScale, yAxisLabel, yTickFormatter, margins]
    )

    const createScales: CreateScalesFn = useCallback(
        (_series: ResolvedSeries[], _labels: string[], dimensions: ChartDimensions): ChartScales => {
            const xScale = buildNumericScale(
                xLogScale,
                sortedPoints.map((point) => point.x),
                [dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth]
            )
            const yScale = buildNumericScale(
                yLogScale,
                sortedPoints.map((point) => point.y),
                [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop]
            )

            const scatterPrivate: ScatterChartPrivate = { __scatterChart: { xScale, yScale } }

            return {
                x: (label: string) => {
                    const point = sortedPoints[Number(label)]
                    return point ? xScale(point.x) : undefined
                },
                y: (value: number) => yScale(value),
                yTicks: () => yScale.ticks(yTickCountForHeight(dimensions.plotHeight)),
                _private: scatterPrivate,
            }
        },
        [xLogScale, yLogScale, sortedPoints]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
            const raw = (scales._private as ScatterChartPrivate | undefined)?.__scatterChart
            if (!raw) {
                return
            }
            const { xScale, yScale } = raw
            const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
            const plotRight = plotLeft + plotWidth
            const plotBottom = plotTop + plotHeight
            const xTicks = xScale.ticks(xTickCountForWidth(plotWidth))

            if (showGrid) {
                ctx.save()
                ctx.strokeStyle = theme.gridColor ?? 'rgba(0, 0, 0, 0.1)'
                ctx.lineWidth = 1
                ctx.beginPath()
                for (const tick of scales.yTicks()) {
                    const y = Math.round(yScale(tick)) + 0.5
                    ctx.moveTo(plotLeft, y)
                    ctx.lineTo(plotRight, y)
                }
                for (const tick of xTicks) {
                    const x = Math.round(xScale(tick)) + 0.5
                    ctx.moveTo(x, plotTop)
                    ctx.lineTo(x, plotBottom)
                }
                ctx.stroke()
                ctx.restore()
            }

            // L-shaped baselines so the continuous plot reads as framed even without the grid.
            const axisLineColor = resolveAxisLineColor(theme)
            if (axisLineColor) {
                ctx.save()
                ctx.strokeStyle = axisLineColor
                ctx.lineWidth = 1
                ctx.beginPath()
                ctx.moveTo(Math.round(plotLeft) + 0.5, plotTop)
                ctx.lineTo(Math.round(plotLeft) + 0.5, plotBottom)
                ctx.moveTo(plotLeft, Math.round(plotBottom) + 0.5)
                ctx.lineTo(plotRight, Math.round(plotBottom) + 0.5)
                ctx.stroke()
                ctx.restore()
            }

            // Numeric x-axis tick labels + title (the base chart draws only the y-axis).
            const axisColor = theme.axisColor ?? 'rgba(0, 0, 0, 0.5)'
            ctx.save()
            ctx.fillStyle = axisColor
            ctx.font = `${AXIS_FONT_SIZE}px -apple-system, system-ui, sans-serif`
            ctx.textAlign = 'center'
            ctx.textBaseline = 'top'
            // Ticks come back ascending; drop any label that would collide with the previous one.
            let lastLabelRight = -Infinity
            for (const tick of xTicks) {
                const x = xScale(tick)
                if (!isFinite(x)) {
                    continue
                }
                const label = xTickFormatter(tick)
                const halfWidth = ctx.measureText(label).width / 2
                if (x - halfWidth < lastLabelRight + X_TICK_MIN_GAP) {
                    continue
                }
                ctx.fillText(label, x, plotBottom + X_TICK_LABEL_GAP)
                lastLabelRight = x + halfWidth
            }
            if (xAxisLabel) {
                ctx.fillText(xAxisLabel, plotLeft + plotWidth / 2, plotBottom + X_AXIS_MARGIN + X_TITLE_GAP)
            }
            ctx.restore()

            const drawCtx: DrawContext = {
                ctx,
                dimensions,
                xScale: scales.x,
                yScale,
                labels: drawLabels,
            }
            for (const s of coloredSeries) {
                drawPoints(drawCtx, s)
            }
        },
        [showGrid, xAxisLabel, xTickFormatter]
    )

    const drawHover = useCallback(
        ({ ctx, scales, series: coloredSeries, labels: drawLabels, hoverIndex, theme }: ChartDrawArgs): boolean => {
            if (hoverIndex < 0) {
                return false
            }
            const raw = (scales._private as ScatterChartPrivate | undefined)?.__scatterChart
            const point = sortedPoints[hoverIndex]
            if (!raw || !point) {
                return false
            }
            const x = scales.x(drawLabels[hoverIndex])
            const y = raw.yScale(point.y)
            if (x == null || !isFinite(x) || !isFinite(y)) {
                return false
            }
            const seriesColor = coloredSeries[0]?.color ?? theme.colors[0]
            drawHighlightPoint(ctx, x, y, seriesColor, theme.backgroundColor ?? '#ffffff', pointRadius)
            return true
        },
        [sortedPoints, pointRadius]
    )

    const renderTooltip = useCallback(
        (ctx: { dataIndex: number }): React.ReactNode => {
            const point = sortedPoints[ctx.dataIndex]
            if (!point) {
                return null
            }
            if (tooltip) {
                return tooltip(point)
            }
            return (
                <ScatterTooltip
                    label={point.label}
                    xLabel={xAxisLabel}
                    yLabel={yAxisLabel}
                    xValue={point.xDisplay ?? xTickFormatter(point.x)}
                    yValue={point.yDisplay ?? defaultNumberFormat(point.y)}
                />
            )
        },
        [sortedPoints, tooltip, xAxisLabel, yAxisLabel, xTickFormatter]
    )

    return (
        <Chart
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={renderTooltip}
            className={className}
            dataAttr={dataAttr}
        />
    )
}

// Roughly one tick per 80px of width / 40px of height, matching the density the base chart's
// y-axis uses, floored so a small plot still shows a couple of ticks.
function xTickCountForWidth(plotWidth: number): number {
    return Math.max(2, Math.floor(plotWidth / 80))
}

function yTickCountForHeight(plotHeight: number): number {
    return Math.max(2, Math.floor(plotHeight / 40))
}
