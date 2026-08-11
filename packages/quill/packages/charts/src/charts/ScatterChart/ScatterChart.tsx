import { scaleLinear, scaleLog } from 'd3-scale'
import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { drawAxes, drawGrid, resolveAxisLineColor, traceScatterMarker } from '../../core/canvas-renderer'
import type { DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { dimColor, resolveCssColor } from '../../core/color-utils'
import { buildValueScale, sanitizeFixedDomain, yTickCountForHeight } from '../../core/scales'
import type { D3YScale } from '../../core/scales'
import type {
    AreaSelectData,
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
    TooltipContext,
} from '../../core/types'
import {
    findNearestPointIndex,
    flattenScatterPoints,
    readScatterLayout,
    scatterValueRange,
    toScatterPrivate,
} from './scatter-layout'
import type { FlatScatterPoint, ScatterPointPosition } from './scatter-layout'
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
/** Extra px past a marker's edge that still counts as hovering it. Big enough that a small dot
 *  doesn't demand pixel-perfect aim, small enough that empty plot area stays empty. */
const HOVER_SLOP_PX = 6
const MARKER_STROKE_WIDTH = 1.25
/** Px per x-axis tick. Wider than the y axis' ~50px because horizontal numeric labels are wide. */
const X_TICK_SPACING_PX = 90
const MAX_X_TICKS = 12

const EMPTY_AXIS_CONFIG: ScatterAxisConfig = {}

/** The x axis is continuous, so there are no category labels for the base chart to render — its
 *  x-axis layer is fed nulls and {@link ScatterXAxisLabels} draws numeric ticks instead. Declared
 *  at module scope so it can't churn the base chart's margin and tick memos. */
const NO_CATEGORY_X_LABELS = (): null => null

function xTickCountForWidth(plotWidth: number): number {
    if (!isFinite(plotWidth) || plotWidth <= 0) {
        return 2
    }
    return Math.max(2, Math.min(MAX_X_TICKS, Math.floor(plotWidth / X_TICK_SPACING_PX)))
}

interface AxisScaleOptions {
    scaleType?: 'linear' | 'log'
    domain?: readonly [number, number]
    startAtZero?: boolean
}

/** Build one axis' scale. A caller-pinned domain is used as-is; otherwise the shared value-scale
 *  builder derives it from the data, so a scatter axis gets the same log, degenerate-range, and
 *  `nice()` handling as every other chart's value axis. */
function buildScatterAxisScale(
    points: FlatScatterPoint[],
    axis: 'x' | 'y',
    pixelRange: [number, number],
    tickCount: number,
    { scaleType = 'linear', domain, startAtZero = false }: AxisScaleOptions
): D3YScale {
    if (domain) {
        const [min, max] = sanitizeFixedDomain(domain)
        // A log scale has no room for a non-positive bound, so such a domain falls back to linear
        // rather than mapping the whole plot to NaN.
        if (scaleType === 'log' && min > 0) {
            return scaleLog().domain([min, max]).range(pixelRange).clamp(true)
        }
        return scaleLinear().domain([min, max]).range(pixelRange)
    }
    return buildValueScale({
        range: scatterValueRange(points, axis),
        valueRange: pixelRange,
        tickCount,
        scaleType,
        floatBaseline: !startAtZero,
    })
}

export interface ScatterChartProps<Meta = unknown> {
    /** One entry per group of points. A single-group scatter is one series. */
    series: ScatterSeries<Meta>[]
    theme: ChartTheme
    config?: ScatterChartConfig<Meta>
    /** Custom tooltip for the hovered point. `ctx.point` is the point under the cursor. */
    tooltip?: (ctx: ScatterTooltipContext<Meta>) => React.ReactNode
    onPointClick?: (point: ScatterPointDatum<Meta>) => void
    /** Enables drag-to-select: the user drags a rectangle and the callback fires once with its
     *  data-space bounds. Feed those back as the axes' `domain` to zoom. */
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
        margins,
    } = config ?? {}
    // Resolved to primitives (and one array each) so an inline `config` object literal — the
    // normal way to call this — can't re-run the scale build on every parent render.
    const { scaleType: xScaleType, domain: xDomain, startAtZero: xStartAtZero, tickFormatter: xTickFormatter } = xAxis
    const { scaleType: yScaleType, domain: yDomain, startAtZero: yStartAtZero, tickFormatter: yTickFormatter } = yAxis

    // Every point from every series, in one x-sorted index space. A point's position here is the
    // `dataIndex` the base chart's labels, tooltips, and click payloads all speak in.
    const points = useMemo(
        () => flattenScatterPoints(series, { xLogScale: xScaleType === 'log', yLogScale: yScaleType === 'log' }),
        [series, xScaleType, yScaleType]
    )
    const labels = useMemo(() => points.map((_, i) => String(i)), [points])

    // Adapter series: one per scatter series, holding its own points' y values at their global
    // indices and a gap (NaN) everywhere else. That gives the base chart what it needs for the
    // legend, the y-margin sizing, and a tooltip whose rows are the series that actually have a
    // point at the hovered index — which, for a scatter, is exactly one.
    const adaptedSeries = useMemo<Series[]>(() => {
        const data = series.map(() => new Array<number>(points.length).fill(NaN))
        for (let i = 0; i < points.length; i++) {
            data[points[i].seriesIndex][i] = points[i].y
        }
        return series.map((s, i) => ({ key: s.key, label: s.label, data: data[i], color: s.color }))
    }, [series, points])

    const { visibleSeries, legendProps } = useChartLegend(adaptedSeries, theme, config?.legend)

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], _labels: string[], dimensions: ChartDimensions): ChartScales => {
            const hidden = new Set(coloredSeries.filter((s) => s.visibility?.excluded).map((s) => s.key))
            const visiblePoints = hidden.size === 0 ? points : points.filter((p) => !hidden.has(p.seriesKey))

            const xTickCount = xTickCountForWidth(dimensions.plotWidth)
            const yTickCount = yTickCountForHeight(dimensions.plotHeight)
            const xScale = buildScatterAxisScale(
                visiblePoints,
                'x',
                [dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth],
                xTickCount,
                { scaleType: xScaleType, domain: xDomain, startAtZero: xStartAtZero }
            )
            const yScale = buildScatterAxisScale(
                visiblePoints,
                'y',
                [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop],
                yTickCount,
                { scaleType: yScaleType, domain: yDomain, startAtZero: yStartAtZero }
            )

            const positions: ScatterPointPosition[] = []
            const xByIndex = new Array<number | undefined>(points.length)
            let maxRadius = 0
            for (let i = 0; i < points.length; i++) {
                const point = points[i]
                if (hidden.has(point.seriesKey)) {
                    continue
                }
                const x = xScale(point.x)
                const y = yScale(point.y)
                if (!isFinite(x) || !isFinite(y)) {
                    continue
                }
                xByIndex[i] = x
                const owner = series[point.seriesIndex]
                const radius = point.radius ?? owner?.pointRadius ?? defaultPointRadius
                maxRadius = Math.max(maxRadius, radius)
                positions.push({
                    index: i,
                    x,
                    y,
                    radius,
                    // Canvas can't resolve `var(--…)`; theme colors already are, consumer ones may not be.
                    color: resolveCssColor(point.color ?? coloredSeries[point.seriesIndex]?.color ?? theme.colors[0]),
                    shape: owner?.shape ?? 'circle',
                })
            }

            return {
                x: (label: string) => xByIndex[Number(label)],
                y: (value: number) => yScale(value),
                yTicks: () => yScale.ticks?.(yTickCount) ?? [],
                _private: toScatterPrivate({
                    xScale,
                    yScale,
                    positions,
                    xByIndex,
                    xTicks: xScale.ticks?.(xTickCount) ?? [],
                    maxRadius,
                }),
            }
        },
        [
            points,
            series,
            xScaleType,
            xDomain,
            xStartAtZero,
            yScaleType,
            yDomain,
            yStartAtZero,
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

            if (showGrid) {
                drawGrid(drawCtx, {
                    gridColor: drawTheme.gridColor,
                    gridDash: drawTheme.gridDashPattern,
                    frame: !axisLineColor,
                    // Unlike a category chart, the cross-axis grid sits at the x scale's numeric
                    // ticks — the set ScatterXAxisLabels labels underneath, minus any it drops to
                    // avoid overlap. Same relationship the y grid has with the y tick labels.
                    categoryTicks: layout.xTicks.map((tick) => layout.xScale(tick)),
                })
            }

            // Fill translucent, stroke opaque: an overlapping cloud reads as density while each
            // marker keeps a crisp edge. A `cross` is strokes only, so it skips the fill.
            const fills = new Map<string, string>()
            ctx.save()
            ctx.lineWidth = MARKER_STROKE_WIDTH
            for (const position of layout.positions) {
                traceScatterMarker(ctx, position.shape, position.x, position.y, position.radius)
                if (position.shape !== 'cross') {
                    let fill = fills.get(position.color)
                    if (fill === undefined) {
                        fill = dimColor(position.color, fillOpacity)
                        fills.set(position.color, fill)
                    }
                    ctx.fillStyle = fill
                    ctx.fill()
                }
                ctx.strokeStyle = position.color
                ctx.stroke()
            }
            ctx.restore()

            if (axisLineColor) {
                drawAxes(drawCtx, { axisColor: axisLineColor })
            }
        },
        [showGrid, showAxisLines, fillOpacity]
    )

    const drawHover = useCallback(({ ctx, scales, hoverIndex, hoverProgress, theme: drawTheme }: ChartDrawArgs) => {
        const position = readScatterLayout(scales)?.positions.find((p) => p.index === hoverIndex)
        if (!position) {
            return false
        }
        ctx.save()
        ctx.globalAlpha = hoverProgress
        // Halo in the chart background first, so the marker lifts off whatever it overlaps, then
        // repaint it opaque at its own size.
        ctx.lineWidth = 3
        ctx.strokeStyle = drawTheme.backgroundColor ?? '#ffffff'
        traceScatterMarker(ctx, position.shape, position.x, position.y, position.radius + 2)
        ctx.stroke()
        ctx.lineWidth = MARKER_STROKE_WIDTH
        ctx.strokeStyle = position.color
        ctx.fillStyle = position.color
        traceScatterMarker(ctx, position.shape, position.x, position.y, position.radius)
        if (position.shape !== 'cross') {
            ctx.fill()
        }
        ctx.stroke()
        ctx.restore()
        return true
    }, [])

    // The base chart hands over the nearest point by x; a scatter needs the nearest in both axes,
    // and needs empty plot area to resolve to nothing at all rather than to a distant point.
    const resolveHoverIndex = useCallback(
        (_index: number, cursor: { x: number; y: number }, scales: ChartScales): number => {
            const layout = readScatterLayout(scales)
            if (!layout) {
                return -1
            }
            return findNearestPointIndex(layout.positions, cursor.x, cursor.y, HOVER_SLOP_PX, layout.maxRadius)
        },
        []
    )

    // A gap (NaN) must stay a gap: the shared default coerces one to 0, which would anchor the
    // tooltip at whatever pixel `0` maps to for every series with no point at this index.
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
            const { seriesKey, seriesIndex, pointIndex, ...rest } = point
            const owner = series[seriesIndex]
            return {
                ...rest,
                seriesKey,
                seriesIndex,
                pointIndex,
                seriesLabel: owner?.label ?? '',
                color: point.color ?? owner?.color ?? theme.colors[seriesIndex % theme.colors.length],
            }
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

    // The core reports the drag in pixels — its label range means nothing on a continuous axis —
    // so invert each edge through the committed scales to get the range in the points' own units.
    const handleAreaSelect = useCallback(
        (data: AreaSelectData, scales: ChartScales): void => {
            const layout = readScatterLayout(scales)
            if (!layout || !onAreaSelect) {
                return
            }
            onAreaSelect({
                x: sanitizeFixedDomain([layout.xScale.invert(data.xPixel0), layout.xScale.invert(data.xPixel1)]),
                // The y pixel range runs top-to-bottom, so its low pixel inverts to the high value.
                y: sanitizeFixedDomain([layout.yScale.invert(data.yPixel1), layout.yScale.invert(data.yPixel0)]),
            })
        },
        [onAreaSelect]
    )

    const baseConfig = useMemo<ChartConfig>(
        () => ({
            xTickFormatter: NO_CATEGORY_X_LABELS,
            yTickFormatter,
            xAxisLabel,
            yAxisLabel,
            hideXAxis: xAxis.hide,
            hideYAxis: yAxis.hide,
            margins,
            tooltip: { enabled: tooltipConfig?.enabled },
        }),
        [yTickFormatter, xAxisLabel, yAxisLabel, xAxis.hide, yAxis.hide, margins, tooltipConfig?.enabled]
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
                tooltip={renderTooltip}
                onPointClick={onPointClick ? handlePointClick : undefined}
                onAreaSelect={onAreaSelect ? handleAreaSelect : undefined}
                className={className}
                dataAttr={dataAttr}
            >
                {!xAxis.hide && <ScatterXAxisLabels tickFormatter={xTickFormatter} />}
                {children}
            </Chart>
        </ChartLegend>
    )
}
