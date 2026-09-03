import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { drawAxes, drawGrid, drawTickMarks, resolveAxisLineColor } from '../../core/canvas-renderer'
import type { DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { applyMarginOverride, DEFAULT_MARGINS } from '../../core/hooks/useChartMargins'
import { sanitizeFixedDomain } from '../../core/scales'
import type {
    AreaSelectData,
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
    TooltipContext,
} from '../../core/types'
import { computeBestFitSegments } from './best-fit'
import { drawBestFitLines, drawScatterHoverMarker, drawScatterMarkers } from './draw-scatter'
import { findNearestPointIndex } from './nearest-point'
import { flattenScatterPoints, toAdapterSeries, toPointDatum } from './scatter-data'
import type { FlatScatterPoint } from './scatter-data'
import { createScatterScales, readScatterLayout } from './scatter-layout'
import { clampToRange, xLabelEdgeReserve } from './scatter-scales'
import { ScatterTooltip } from './ScatterTooltip'
import { ScatterXAxisLabels } from './ScatterXAxisLabels'
import type {
    ScatterAreaSelection,
    ScatterAxisConfig,
    ScatterChartConfig,
    ScatterPointDatum,
    ScatterSeries,
    ScatterTooltipContext,
} from './types'

const DEFAULT_POINT_RADIUS = 3.5
const DEFAULT_FILL_OPACITY = 0.7

const EMPTY_AXIS_CONFIG: ScatterAxisConfig = {}

/** Blanks the base chart's category x-axis layer, which {@link ScatterXAxisLabels} replaces. At
 *  module scope so it can't churn the base chart's margin and tick memos. */
const NO_CATEGORY_X_LABELS = (): null => null

export interface ScatterChartProps<Meta = unknown> {
    series: ScatterSeries<Meta>[]
    theme: ChartTheme
    config?: ScatterChartConfig<Meta>
    tooltip?: (ctx: ScatterTooltipContext<Meta>) => React.ReactNode
    onPointClick?: (point: ScatterPointDatum<Meta>) => void
    /** Fires once per completed drag. Feed its bounds back as the axes' `domain` to zoom. */
    onAreaSelect?: (selection: ScatterAreaSelection) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function ScatterChart<Meta = unknown>({ onError, ...rest }: ScatterChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <ScatterChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function ScatterChartInner<Meta = unknown>({
    series,
    theme,
    config,
    tooltip,
    onPointClick,
    onAreaSelect,
    className,
    dataAttr,
    children,
}: Omit<ScatterChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        xAxis = EMPTY_AXIS_CONFIG,
        yAxis = EMPTY_AXIS_CONFIG,
        pointRadius: defaultPointRadius = DEFAULT_POINT_RADIUS,
        fillOpacity = DEFAULT_FILL_OPACITY,
        showGrid = true,
        showAxisLines = true,
        showTickMarks = true,
        showCrosshair = true,
        showBestFit = false,
        margins,
    } = config ?? {}
    // Destructured to primitives, so an inline `config` literal can't re-run the scale build.
    const { scaleType: xScaleType, domain: xDomain, startAtZero: xStartAtZero, tickFormatter: xTickFormatter } = xAxis
    const { scaleType: yScaleType, domain: yDomain, startAtZero: yStartAtZero, tickFormatter: yTickFormatter } = yAxis

    const points = useMemo(
        () => flattenScatterPoints(series, { xLogScale: xScaleType === 'log', yLogScale: yScaleType === 'log' }),
        [series, xScaleType, yScaleType]
    )
    const labels = useMemo(() => points.map((_, i) => String(i)), [points])

    const adaptedSeries = useMemo(() => toAdapterSeries(series, points), [series, points])

    const { visibleSeries, legendProps } = useChartLegend(adaptedSeries, theme, config?.legend)

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], _labels: string[], dimensions: ChartDimensions): ChartScales =>
            createScatterScales({
                points,
                seriesStyles: series,
                coloredSeries,
                dimensions,
                xAxis: { scaleType: xScaleType, domain: xDomain, startAtZero: xStartAtZero },
                yAxis: { scaleType: yScaleType, domain: yDomain, startAtZero: yStartAtZero },
                xTickFormatter,
                defaultPointRadius,
                fallbackColor: theme.colors[0],
            }),
        [
            points,
            series,
            xScaleType,
            xDomain,
            xStartAtZero,
            yScaleType,
            yDomain,
            yStartAtZero,
            xTickFormatter,
            defaultPointRadius,
            theme.colors,
        ]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, theme: drawTheme }: ChartDrawArgs) => {
            const layout = readScatterLayout(scales)
            if (!layout) {
                return
            }
            const drawCtx: DrawContext = { ctx, dimensions, xScale: scales.x, yScale: layout.yScale, labels: [] }
            const axisLineColor = showAxisLines ? resolveAxisLineColor(drawTheme) : undefined
            const xTickPixels = layout.xTicks.map((tick) => tick.x)

            if (showGrid) {
                drawGrid(drawCtx, {
                    gridColor: drawTheme.gridColor,
                    gridDash: drawTheme.gridDashPattern,
                    frame: !axisLineColor,
                    categoryTicks: xTickPixels,
                })
            }

            // The base chart's x tick marks come off category labels, so draw this axis' own here.
            if (showTickMarks) {
                drawTickMarks(ctx, dimensions, { xs: xTickPixels, ys: [] }, axisLineColor)
            }

            drawScatterMarkers(ctx, layout.positions, fillOpacity)

            // Over the markers: in a dense cloud, which is where a fit line earns its place, drawing
            // it underneath would bury it.
            if (showBestFit) {
                drawBestFitLines(ctx, computeBestFitSegments(layout.positions, layout.seriesColors), dimensions)
            }

            if (axisLineColor) {
                drawAxes(drawCtx, { axisColor: axisLineColor })
            }
        },
        [showGrid, showAxisLines, showTickMarks, fillOpacity, showBestFit]
    )

    const drawHover = useCallback(({ ctx, scales, hoverIndex, hoverProgress, theme: drawTheme }: ChartDrawArgs) => {
        const position = readScatterLayout(scales)?.positions.find((p) => p.index === hoverIndex)
        if (!position) {
            return false
        }
        drawScatterHoverMarker(ctx, position, drawTheme.backgroundColor ?? '#ffffff', hoverProgress)
        return true
    }, [])

    // The base chart resolves by x alone, which can't tell points stacked at one x apart.
    const resolveHoverIndex = useCallback(
        (_index: number, cursor: { x: number; y: number }, scales: ChartScales): number => {
            const layout = readScatterLayout(scales)
            if (!layout) {
                return -1
            }
            return findNearestPointIndex(layout.positions, cursor.x, cursor.y, layout.maxRadius)
        },
        []
    )

    // A gap must stay NaN. The shared default coerces one to 0, anchoring the tooltip at whatever
    // pixel `0` maps to for every series with no point at this index.
    const resolveValue: ResolveValueFn = useCallback((s, dataIndex) => {
        const value = s.data[dataIndex]
        return typeof value === 'number' && isFinite(value) ? value : NaN
    }, [])

    const resolvePoint = useCallback(
        (dataIndex: number): ScatterPointDatum<Meta> | null => {
            const point = points[dataIndex] as FlatScatterPoint<Meta> | undefined
            if (!point) {
                return null
            }
            const { seriesIndex } = point
            return toPointDatum(point, series[seriesIndex], theme.colors[seriesIndex % theme.colors.length])
        },
        [points, series, theme.colors]
    )

    const tooltipConfig = config?.tooltip
    const xAxisLabel = xAxis.label
    const yAxisLabel = yAxis.label
    const renderTooltip = useCallback(
        (ctx: TooltipContext): React.ReactNode => {
            const point = resolvePoint(ctx.dataIndex)
            if (!point) {
                return null
            }
            if (tooltip) {
                return tooltip({ ...ctx, point })
            }
            return (
                <ScatterTooltip
                    point={point}
                    header={tooltipConfig?.labelFormatter?.(point)}
                    xLabel={xAxisLabel}
                    yLabel={yAxisLabel}
                    xValue={tooltipConfig?.xFormatter?.(point.x, point) ?? xTickFormatter?.(point.x)}
                    yValue={tooltipConfig?.yFormatter?.(point.y, point) ?? yTickFormatter?.(point.y)}
                />
            )
        },
        [resolvePoint, tooltip, tooltipConfig, xAxisLabel, yAxisLabel, xTickFormatter, yTickFormatter]
    )

    const handlePointClick = useCallback(
        (data: PointClickData): void => {
            const point = resolvePoint(data.dataIndex)
            if (point) {
                onPointClick?.(point)
            }
        },
        [onPointClick, resolvePoint]
    )

    // The core's label range means nothing on a continuous axis, so invert its raw pixels instead.
    const handleAreaSelect = useCallback(
        (data: AreaSelectData, scales: ChartScales): void => {
            const layout = readScatterLayout(scales)
            if (!layout || !onAreaSelect) {
                return
            }
            const { xScale, yScale } = layout
            onAreaSelect({
                x: sanitizeFixedDomain([
                    xScale.invert(clampToRange(data.xPixel0, xScale)),
                    xScale.invert(clampToRange(data.xPixel1, xScale)),
                ]),
                // The y pixel range runs top-to-bottom, so its low pixel inverts to the high value.
                y: sanitizeFixedDomain([
                    yScale.invert(clampToRange(data.yPixel1, yScale)),
                    yScale.invert(clampToRange(data.yPixel0, yScale)),
                ]),
            })
        },
        [onAreaSelect]
    )

    // Otherwise the y gutter is sized from the adapter series, which stop short of a pinned domain.
    const valueRangeSeries = useMemo<Series[] | undefined>(() => {
        if (!yDomain) {
            return undefined
        }
        return [{ key: '__scatter_y_domain', label: '', data: sanitizeFixedDomain(yDomain) }]
    }, [yDomain])

    const resolvedMargins = useMemo<Partial<ChartMargins> | undefined>(() => {
        if (xAxis.hide) {
            return margins
        }
        // Right side only, since the y-axis gutter already reserves more than half a tick label.
        const computed: Partial<ChartMargins> = {
            right: Math.max(DEFAULT_MARGINS.right, xLabelEdgeReserve(points, xDomain, xTickFormatter)),
        }
        return margins ? applyMarginOverride(computed, margins) : computed
    }, [xAxis.hide, margins, points, xDomain, xTickFormatter])

    const baseConfig = useMemo<ChartConfig>(
        () => ({
            xTickFormatter: NO_CATEGORY_X_LABELS,
            yTickFormatter,
            xAxisLabel,
            yAxisLabel,
            hideXAxis: xAxis.hide,
            hideYAxis: yAxis.hide,
            margins: resolvedMargins,
            showTickMarks,
            showCrosshair,
            tooltip: { enabled: tooltipConfig?.enabled, placement: tooltipConfig?.placement ?? 'cursor' },
        }),
        [
            yTickFormatter,
            xAxisLabel,
            yAxisLabel,
            xAxis.hide,
            yAxis.hide,
            resolvedMargins,
            showTickMarks,
            showCrosshair,
            tooltipConfig?.enabled,
            tooltipConfig?.placement,
        ]
    )

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-scatter-legend">
            <Chart
                series={visibleSeries}
                labels={labels}
                config={baseConfig}
                theme={theme}
                createScales={createScales}
                drawStatic={drawStatic}
                drawHover={drawHover}
                resolveHoverIndex={resolveHoverIndex}
                resolveValue={resolveValue}
                valueRangeSeries={valueRangeSeries}
                tooltip={renderTooltip}
                onPointClick={onPointClick ? handlePointClick : undefined}
                onAreaSelect={onAreaSelect ? handleAreaSelect : undefined}
                className={className}
                dataAttr={dataAttr}
            >
                {!xAxis.hide && <ScatterXAxisLabels />}
                {children}
            </Chart>
        </ChartLegend>
    )
}
