import React, { useCallback, useEffect, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { drawAxes, drawGrid, drawTickMarks, resolveAxisLineColor } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { useChartHover, useChartLayout } from '../../core/chart-context'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import {
    estimateHistogramPercentile,
    histogramColumnAtPixel,
    histogramRangeToPixels,
    histogramTotals,
    prepareHistogramBins,
    snapPixelRangeToBins,
} from '../../core/histogram-layout'
import type { PreparedHistogramBin } from '../../core/histogram-layout'
import { applyMarginOverride } from '../../core/hooks/useChartMargins'
import { SINGLE_LABEL_MIN_DRAG_PX } from '../../core/interaction'
import type {
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    DragRect,
    PixelRangeSelectData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
    TooltipContext,
} from '../../core/types'
import { humanFriendlyNumber } from '../../utils/format'
import { useYTickFormatter } from '../../utils/use-axis-formatters'
import {
    drawHistogramBars,
    drawHistogramHover,
    drawHistogramSelectionBand,
    drawHistogramSelectionEdges,
} from './draw-histogram'
import {
    createHistogramScales,
    readHistogramColors,
    readHistogramHoverColors,
    readHistogramLayout,
} from './histogram-scales'
import { HistogramMarkers, MARKER_LABEL_MARGIN, type ResolvedHistogramMarker } from './HistogramMarkers'
import { HistogramTooltip } from './HistogramTooltip'
import { HistogramXAxisLabels } from './HistogramXAxisLabels'
import type {
    HistogramAxisConfig,
    HistogramBin,
    HistogramConfig,
    HistogramRange,
    HistogramSeries,
    HistogramTooltipContext,
} from './types'

const DEFAULT_SERIES_KEY = 'count'
const DEFAULT_MIN_BAR_HEIGHT = 1
const DEFAULT_COLUMN_COLOR = 'rgba(0, 0, 0, 0.5)'
const EMPTY_AXIS_CONFIG: HistogramAxisConfig = {}

/** Blanks the base chart's category x-axis layer, which {@link HistogramXAxisLabels} replaces. At
 *  module scope so it can't churn the base chart's margin and tick memos. */
const NO_CATEGORY_X_LABELS = (): null => null

export interface HistogramProps<Meta = unknown> {
    /** Bins with real edges, in any order. Widths may differ, as with log-spaced latency buckets. */
    bins: HistogramBin<Meta>[]
    /** Stacked layers, each with one count per bin. Omit to draw `bins[i].count` as one series. */
    series?: HistogramSeries[]
    /** Colors and chrome, from `useChartTheme()`. */
    theme: ChartTheme
    config?: HistogramConfig
    /** Draws a selection band over this range and fades the bars outside it. Controlled: pass back
     *  what `onRangeSelect` reports, and `null` to clear. */
    selectedRange?: HistogramRange | null
    /** Enables drag to select. Fires once per completed drag with the range snapped outward to whole
     *  bins: `min` is the first bin's `start` and `max` the last bin's exclusive `end`. */
    onRangeSelect?: (range: HistogramRange) => void
    /** Fires when Escape is pressed while the pointer is over a bin and a range is selected. */
    onRangeClear?: () => void
    /** Replaces the default tooltip content. */
    tooltip?: (ctx: HistogramTooltipContext<Meta>) => React.ReactNode
    /** Class applied to the chart wrapper. */
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    /** Custom overlays, rendered over the plot. Read the layout with `useChartLayout()`. */
    children?: React.ReactNode
    /** Called when rendering throws, instead of unmounting the parent. */
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function Histogram<Meta = unknown>({ onError, ...rest }: HistogramProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <HistogramInner {...rest} />
        </ChartErrorBoundary>
    )
}

function defaultFormat(value: number): string {
    return humanFriendlyNumber(value)
}

/** Clears the selection on Escape, only while the pointer is over a bin so a key meant for a dialog
 *  elsewhere on the page leaves the chart alone. */
function EscapeToClear({ onClear }: { onClear: () => void }): null {
    const { hoverIndex } = useChartHover()
    const active = hoverIndex >= 0
    useEffect(() => {
        if (!active) {
            return
        }
        const handler = (e: KeyboardEvent): void => {
            if (e.key === 'Escape' && !e.defaultPrevented) {
                onClear()
            }
        }
        window.addEventListener('keydown', handler)
        return () => window.removeEventListener('keydown', handler)
    }, [active, onClear])
    return null
}

interface ColumnTooltipProps<Meta> {
    ctx: TooltipContext
    prepared: PreparedHistogramBin<HistogramBin<Meta>>[]
    totals: number[]
    cumulative: number[]
    grandTotal: number
    render: (ctx: HistogramTooltipContext<Meta>) => React.ReactNode
}

function sumFinite(values: number[], from: number, to: number): number {
    let sum = 0
    for (let i = from; i <= to; i++) {
        const value = values[i]
        sum += isFinite(value) && value > 0 ? value : 0
    }
    return sum
}

/** Describes the hovered column, which spans several bins when they are narrower than a pixel. */
function ColumnTooltip<Meta>({
    ctx,
    prepared,
    totals,
    cumulative,
    grandTotal,
    render,
}: ColumnTooltipProps<Meta>): React.ReactElement | null {
    const { scales } = useChartLayout()
    const layout = readHistogramLayout(scales)
    const column = layout?.bins[layout.columnOf[ctx.dataIndex] ?? -1]
    const first = column?.index ?? ctx.dataIndex
    const last = column?.lastIndex ?? ctx.dataIndex
    const sources = prepared.slice(first, last + 1)
    if (!sources.length) {
        return null
    }
    const count = sumFinite(totals, first, last)
    const merged = sources.length > 1
    const histogramCtx: HistogramTooltipContext<Meta> = {
        ...ctx,
        seriesData: merged
            ? ctx.seriesData.map((entry) => ({ ...entry, value: sumFinite(entry.series.data, first, last) }))
            : ctx.seriesData,
        bin: merged
            ? { start: sources[0].start, end: sources[sources.length - 1].end, count }
            : { ...sources[0].source, start: sources[0].start, end: sources[0].end },
        bins: sources.map((bin) => bin.source),
        count,
        fraction: grandTotal > 0 ? count / grandTotal : 0,
        cumulativeFraction: grandTotal > 0 ? (cumulative[last] ?? 0) / grandTotal : 0,
    }
    return <>{render(histogramCtx)}</>
}

function HistogramInner<Meta = unknown>({
    bins,
    series,
    theme,
    config,
    selectedRange,
    onRangeSelect,
    onRangeClear,
    tooltip,
    className,
    dataAttr,
    children,
}: Omit<HistogramProps<Meta>, 'onError'>): React.ReactElement {
    const {
        xAxis = EMPTY_AXIS_CONFIG,
        yAxis = EMPTY_AXIS_CONFIG,
        markers,
        showGrid = true,
        showAxisLines = true,
        showTickMarks = true,
        minBarHeight = DEFAULT_MIN_BAR_HEIGHT,
        legend,
        tooltip: tooltipConfig,
        margins,
    } = config ?? {}

    const xFormatter = useYTickFormatter(xAxis)
    const yFormatter = useYTickFormatter(yAxis)
    const xScaleType = xAxis.scaleType
    const yScaleType = yAxis.scaleType

    const prepared = useMemo(() => prepareHistogramBins(bins), [bins])
    const labels = useMemo(() => prepared.map((_, i) => String(i)), [prepared])

    const chartSeries = useMemo<Series[]>(() => {
        const source: HistogramSeries[] = series ?? [
            { key: DEFAULT_SERIES_KEY, label: yAxis.label ?? 'Count', data: bins.map((bin) => bin.count ?? 0) },
        ]
        return source.map((s) => ({
            key: s.key,
            label: s.label,
            color: s.color,
            data: prepared.map((bin) => s.data[bin.sourceIndex] ?? 0),
        }))
    }, [series, bins, prepared, yAxis.label])

    const { visibleSeries, legendProps } = useChartLegend(chartSeries, theme, legend)

    const totals = useMemo(
        () =>
            histogramTotals(
                visibleSeries.map((s) => ({ data: s.data, excluded: s.visibility?.excluded })),
                prepared.length
            ),
        [prepared, visibleSeries]
    )
    const grandTotal = useMemo(() => totals.reduce((sum, total) => sum + total, 0), [totals])
    const cumulative = useMemo(() => {
        let running = 0
        return totals.map((total) => (running += total))
    }, [totals])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], _labels: string[], dimensions: ChartDimensions): ChartScales =>
            createHistogramScales({
                bins: prepared,
                series: coloredSeries,
                dimensions,
                xScaleType,
                yScaleType,
                xTickFormatter: xFormatter,
                minBarHeight,
            }),
        [prepared, xScaleType, yScaleType, xFormatter, minBarHeight]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, theme: drawTheme }: ChartDrawArgs) => {
            const layout = readHistogramLayout(scales)
            if (!layout) {
                return
            }
            const axisLineColor = showAxisLines ? resolveAxisLineColor(drawTheme) : undefined
            const xTickPixels = xAxis.hide ? [] : layout.xTicks.map((tick) => tick.x)
            if (showGrid) {
                drawGrid(
                    { ctx, dimensions, yScale: layout.yScale },
                    {
                        gridColor: drawTheme.gridColor,
                        gridDash: drawTheme.gridDashPattern,
                        frame: !axisLineColor,
                        valueTicks: layout.yTicks,
                        categoryTicks: xTickPixels,
                    }
                )
            }
            if (showTickMarks) {
                drawTickMarks(ctx, dimensions, { xs: xTickPixels, ys: [] }, axisLineColor)
            }

            const span = selectedRange ? histogramRangeToPixels(layout, selectedRange) : null
            const isDimmed = selectedRange
                ? (column: number): boolean =>
                      layout.bins[column].end <= selectedRange.min || layout.bins[column].start >= selectedRange.max
                : undefined
            if (span) {
                drawHistogramSelectionBand(ctx, dimensions, span)
            }
            drawHistogramBars(ctx, layout.segments, readHistogramColors(scales), isDimmed)
            if (span) {
                drawHistogramSelectionEdges(ctx, dimensions, span)
            }
            if (axisLineColor) {
                drawAxes({ ctx, dimensions }, { axisColor: axisLineColor })
            }
        },
        [showAxisLines, showGrid, showTickMarks, xAxis.hide, selectedRange]
    )

    const drawHover = useCallback(
        ({ ctx, dimensions, scales, hoverIndex, hoverProgress, theme: drawTheme }: ChartDrawArgs) => {
            const layout = readHistogramLayout(scales)
            if (!layout || hoverIndex < 0) {
                return false
            }
            const columnColor = drawTheme.crosshairColor ?? drawTheme.axisColor ?? DEFAULT_COLUMN_COLOR
            const colors = readHistogramHoverColors(scales)
            return drawHistogramHover(ctx, layout, dimensions, hoverIndex, colors, columnColor, hoverProgress)
        },
        []
    )

    // The base chart picks the nearest bin center, which misses on bins of unequal width.
    const resolveHoverIndex = useCallback((_index: number, cursor: { x: number }, scales: ChartScales): number => {
        const layout = readHistogramLayout(scales)
        return (layout && histogramColumnAtPixel(layout, cursor.x)?.index) ?? -1
    }, [])

    const resolvePositionValue: ResolveValueFn = useCallback((_s, dataIndex) => totals[dataIndex] ?? 0, [totals])

    const handlePixelRangeSelect = useCallback(
        (data: PixelRangeSelectData, scales: ChartScales): void => {
            const layout = readHistogramLayout(scales)
            const snapped = layout ? snapPixelRangeToBins(layout, data.xPixel0, data.xPixel1) : null
            if (snapped) {
                onRangeSelect?.({ min: snapped.first.start, max: snapped.last.end })
            }
        },
        [onRangeSelect]
    )

    const snapDragRect = useCallback((rect: DragRect, scales: ChartScales): DragRect => {
        const layout = readHistogramLayout(scales)
        const wideEnough = Math.abs(rect.x1 - rect.x0) >= SINGLE_LABEL_MIN_DRAG_PX
        const snapped = layout && wideEnough ? snapPixelRangeToBins(layout, rect.x0, rect.x1) : null
        return snapped ? { x0: snapped.first.x0, x1: snapped.last.x1 } : { x0: rect.x0, x1: rect.x0 }
    }, [])

    const formatX = xFormatter ?? defaultFormat
    const formatCount = yFormatter ?? defaultFormat

    const renderContent = useCallback(
        (ctx: HistogramTooltipContext<Meta>): React.ReactNode =>
            tooltip ? tooltip(ctx) : <HistogramTooltip ctx={ctx} formatX={formatX} formatCount={formatCount} />,
        [tooltip, formatX, formatCount]
    )
    const renderTooltip = useCallback(
        (ctx: TooltipContext): React.ReactNode => (
            <ColumnTooltip
                ctx={ctx}
                prepared={prepared}
                totals={totals}
                cumulative={cumulative}
                grandTotal={grandTotal}
                render={renderContent}
            />
        ),
        [prepared, totals, cumulative, grandTotal, renderContent]
    )

    const resolvedMarkers = useMemo<ResolvedHistogramMarker[]>(() => {
        if (!markers?.length) {
            return []
        }
        const resolved: ResolvedHistogramMarker[] = []
        markers.forEach((marker, i) => {
            const value =
                marker.percentile !== undefined
                    ? estimateHistogramPercentile(prepared, totals, marker.percentile)
                    : marker.value
            if (value === undefined || !isFinite(value)) {
                return
            }
            resolved.push({
                key: `${i}`,
                label: marker.label ?? `p${marker.percentile}`,
                value,
                valueText: formatX(value),
                color: marker.color,
            })
        })
        return resolved
    }, [markers, prepared, totals, formatX])

    // Gutter sizing reads series values, which for a stack are per layer rather than the bar's height.
    const valueRangeSeries = useMemo<Series[]>(() => [{ key: '__histogram_totals', label: '', data: totals }], [totals])

    const hasMarkers = resolvedMarkers.length > 0
    const resolvedMargins = useMemo<Partial<ChartMargins> | undefined>(() => {
        if (!hasMarkers) {
            return margins
        }
        const computed: Partial<ChartMargins> = { top: MARKER_LABEL_MARGIN }
        return margins ? applyMarginOverride(computed, margins) : computed
    }, [hasMarkers, margins])

    const baseConfig = useMemo<ChartConfig>(
        () => ({
            xTickFormatter: NO_CATEGORY_X_LABELS,
            yTickFormatter: yFormatter,
            xAxisLabel: xAxis.label,
            yAxisLabel: yAxis.label,
            hideXAxis: xAxis.hide,
            hideYAxis: yAxis.hide,
            margins: resolvedMargins,
            showTickMarks,
            showCrosshair: false,
            tooltip: { enabled: tooltipConfig?.enabled, placement: tooltipConfig?.placement ?? 'cursor' },
        }),
        [
            yFormatter,
            xAxis.label,
            yAxis.label,
            xAxis.hide,
            yAxis.hide,
            resolvedMargins,
            showTickMarks,
            tooltipConfig?.enabled,
            tooltipConfig?.placement,
        ]
    )

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-histogram-legend">
            <Chart
                series={visibleSeries}
                labels={labels}
                config={baseConfig}
                theme={theme}
                createScales={createScales}
                drawStatic={drawStatic}
                drawHover={drawHover}
                resolveHoverIndex={resolveHoverIndex}
                resolvePositionValue={resolvePositionValue}
                valueRangeSeries={valueRangeSeries}
                tooltip={renderTooltip}
                onPixelRangeSelect={onRangeSelect ? handlePixelRangeSelect : undefined}
                snapDragRect={snapDragRect}
                className={className}
                dataAttr={dataAttr}
            >
                {!xAxis.hide && <HistogramXAxisLabels />}
                {hasMarkers && <HistogramMarkers markers={resolvedMarkers} />}
                {onRangeClear && selectedRange && <EscapeToClear onClear={onRangeClear} />}
                {children}
            </Chart>
        </ChartLegend>
    )
}
