import React, { useMemo } from 'react'

import {
    AxisLabels,
    computeVisibleValueTicks,
    computeVisibleXLabels,
    computeVisibleYTicks,
} from '../overlays/AxisLabels'
import { AxisTitles } from '../overlays/AxisTitles'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { normalizeAxisLabel } from '../utils/axis-labels'
import {
    composeDrawHoverWithCrosshair,
    composeDrawHoverWithSelection,
    drawTickMarks,
    resolveAxisLineColor,
    type TickMarkCoords,
} from './canvas-renderer'
import { ChartHoverContext, ChartLayoutContext } from './chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from './chart-context'
import { ChartShell, countVisibleSeries, useCanvasBounds, useColoredSeries } from './chart-shell'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useChartInteraction } from './hooks/useChartInteraction'
import { useChartMargins } from './hooks/useChartMargins'
import { useLatest } from './hooks/useLatest'
import { useResolvedYFormatter } from './hooks/useResolvedYFormatters'
import { useStableResolveValue } from './hooks/useStableResolveValue'
import { useYAxisMaps } from './hooks/useYAxisMaps'
import type {
    ChartConfig,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    DateRangeZoomData,
    DrawHoverResult,
    PointClickData,
    ResolveValueFn,
    Series,
    TooltipContext,
} from './types'
import { computeYAxisGutters, type Gutter } from './y-axis-gutters'

const DEFAULT_AXIS_COLOR = 'rgba(0, 0, 0, 0.5)'
const DEFAULT_HOVER_ANIMATION_MS = 150

function resolveHoverAnimationMs(animateHover: boolean | number | undefined): number {
    if (animateHover === true) {
        return DEFAULT_HOVER_ANIMATION_MS
    }
    if (typeof animateHover === 'number') {
        return animateHover
    }
    return 0
}

export interface ChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: ChartConfig
    theme: ChartTheme
    createScales: CreateScalesFn
    /** Static layer — grid, lines, areas, points. Redrawn only when chart inputs change. */
    drawStatic: (args: ChartDrawArgs) => void
    /** Hover overlay — highlight rings only. Return `false` if nothing was drawn (the
     *  hover-fade timer pauses while invisible). */
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** Enables x-axis drag-to-zoom. Fired with the label range the user dragged across.
     *  x-axis only — has no effect on charts with a vertical (`interactionAxis: 'y'`) interaction. */
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    /** Resolves the y-value to *display* for a series at a given index. Defaults to
     *  series.data[index]. Identity is read live for tooltip values, but the pinned-tooltip
     *  rebuild only refires when `series`, `labels`, or `scales` change. Callers that
     *  derive values from data not reflected in those (e.g. an external "%" toggle)
     *  should ensure that toggle also updates `series` or the chart's scales — otherwise
     *  a held pin will keep showing values from the previous resolver. */
    resolveValue?: ResolveValueFn
    /** Value used to *anchor* the tooltip and value-label overlays per series. Defaults to
     *  `resolveValue`. Stacked charts pass the stacked-top resolver here so overlays land at the
     *  visual top of each segment, while each tooltip row still shows that series's own value
     *  via `resolveValue`. */
    resolvePositionValue?: ResolveValueFn
    /** Resolves the stacked bottom value per series — used to compute segment midpoints for
     *  tooltip closest-series detection. Only bar charts provide this. */
    resolveBottomValue?: ResolveValueFn
    /** Required for horizontal orientation — maps labels to the coordinate on the categorical
     *  axis (y in horizontal mode). Should be referentially stable; non-stable identities
     *  invalidate the interaction memo on every render. */
    labelToCoord?: (label: string) => number | undefined
    /** Override the series fed into value-axis tick sizing (`useChartMargins`). Use when the
     *  visible series's `data[i]` doesn't span the y-domain — e.g. BoxPlot passes synthetic
     *  whisker min/max samples so the y-tick column fits the real value range, not just the
     *  medians it draws on `series.data`. */
    valueRangeSeries?: Series[]
    /** Chart-type seam: rewrite the click payload (e.g. resolve the stacked segment under the
     *  cursor) before it reaches `onPointClick`, using the committed `scales` from this render.
     *  Chart-type adapters provide this; consumers do not. */
    wrapClickData?: (data: PointClickData<Meta>, scales: ChartScales) => PointClickData<Meta>
}

export function Chart<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    createScales: createScalesFn,
    drawStatic,
    drawHover,
    tooltip: renderTooltipProp,
    onPointClick,
    onDateRangeZoom,
    className,
    dataAttr,
    children,
    resolveValue,
    resolvePositionValue,
    resolveBottomValue,
    labelToCoord,
    valueRangeSeries,
    wrapClickData,
}: ChartProps<Meta>): React.ReactElement {
    const {
        xTickFormatter,
        yTickFormatter,
        hideXAxis = false,
        hideYAxis = false,
        xAxisLabel,
        yAxisLabel,
        tooltip: tooltipConfig,
        showCrosshair = false,
        showTickMarks = false,
        axisOrientation = 'vertical',
        isPercent = false,
        animateHover,
        margins: marginsOverride,
        maxCategoryLabelWidth,
        yAxes,
    } = config ?? {}

    const {
        formatters: yAxisFormatters,
        positions: yAxisPositions,
        titles: yAxisTitles,
    } = useYAxisMaps(yAxes, yAxisLabel)
    const hoverAnimationMs = resolveHoverAnimationMs(animateHover)
    const interactionAxis: 'x' | 'y' = axisOrientation === 'horizontal' ? 'y' : 'x'
    const {
        enabled: showTooltip = true,
        pinnable: pinnableTooltip = false,
        resolveClickToNearestSeries = false,
        placement: tooltipPlacement = 'follow-data',
        valueFormatter: tooltipValueFormatter,
        labelFormatter: tooltipLabelFormatter,
        showTotal: tooltipShowTotal,
        totalLabel: tooltipTotalLabel,
        totalFormatter: tooltipTotalFormatter,
        sortedByValue: tooltipSortedByValue,
    } = tooltipConfig ?? {}

    // No render prop: render DefaultTooltip with config.tooltip's formatters (all undefined → bare default).
    const renderTooltip = useMemo<(ctx: TooltipContext<Meta>) => React.ReactNode>(
        () =>
            renderTooltipProp ??
            ((ctx: TooltipContext<Meta>) => (
                <DefaultTooltip
                    {...ctx}
                    valueFormatter={tooltipValueFormatter}
                    labelFormatter={tooltipLabelFormatter}
                    showTotal={tooltipShowTotal}
                    totalLabel={tooltipTotalLabel}
                    totalFormatter={tooltipTotalFormatter}
                    sortedByValue={tooltipSortedByValue}
                />
            )),
        [
            renderTooltipProp,
            tooltipValueFormatter,
            tooltipLabelFormatter,
            tooltipShowTotal,
            tooltipTotalLabel,
            tooltipTotalFormatter,
            tooltipSortedByValue,
        ]
    )

    const margins = useChartMargins({
        series,
        labels,
        hideXAxis,
        hideYAxis,
        xAxisLabel,
        xTickFormatter,
        yTickFormatter,
        axisOrientation,
        override: marginsOverride,
        valueRangeSeries,
        maxCategoryLabelWidth,
        yAxisFormatters,
        yAxisPositions,
        yAxisTitles,
    })

    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({ margins })

    const coloredSeries = useColoredSeries<Meta>(series, theme)

    const scales = useMemo<ChartScales | null>(() => {
        if (!dimensions) {
            return null
        }
        return createScalesFn(coloredSeries, labels, dimensions)
    }, [coloredSeries, labels, dimensions, createScalesFn])

    const resolvedYFormatter = useResolvedYFormatter(scales, yTickFormatter)

    // Computed once and shared with AxisLabels and AxisTitles via context so they can't drift.
    const yGutters = useMemo<Gutter[]>(
        () =>
            !scales || hideYAxis || axisOrientation === 'horizontal'
                ? []
                : computeYAxisGutters(scales, {
                      yTicks: scales.yTicks(),
                      yTickFormatter: resolvedYFormatter,
                      userYTickFormatter: yTickFormatter,
                      yAxisFormatters,
                      titles: yAxisTitles,
                  }),
        [scales, hideYAxis, axisOrientation, resolvedYFormatter, yTickFormatter, yAxisFormatters, yAxisTitles]
    )

    // Mirrors AxisLabels' visible-label computation (same pure helpers, same inputs) so every tick
    // mark sits next to a rendered label. Drawn on canvas rather than as DOM overlays so ticks share
    // the axis/grid stroke snapping and can't drift a pixel against those lines.
    const tickMarkCoords = useMemo<TickMarkCoords | null>(() => {
        if (!showTickMarks || !scales || !dimensions) {
            return null
        }
        if (axisOrientation === 'horizontal') {
            const labelToY = labelToCoord ?? scales.x
            const ys = hideYAxis
                ? []
                : labels
                      .filter((label, i) => !xTickFormatter || xTickFormatter(label, i) !== null)
                      .map((label) => labelToY(label))
                      .filter((y): y is number => y != null && isFinite(y))
                      .map((y) => ({ y, side: 'left' as const, offset: 0 }))
            const xs = hideXAxis
                ? []
                : computeVisibleValueTicks(scales.yTicks(), scales.y, resolvedYFormatter).map((t) => t.x)
            return { xs, ys }
        }
        const xs = hideXAxis
            ? []
            : computeVisibleXLabels(labels, scales.x, xTickFormatter, maxCategoryLabelWidth).map((l) => l.x)
        const ys = yGutters.flatMap((gutter) =>
            computeVisibleYTicks(gutter.ticks, gutter.scale)
                .map((tick) => gutter.scale(tick))
                .filter((y) => isFinite(y))
                .map((y) => ({ y, side: gutter.side, offset: gutter.offset }))
        )
        return { xs, ys }
    }, [
        showTickMarks,
        scales,
        dimensions,
        axisOrientation,
        labels,
        xTickFormatter,
        maxCategoryLabelWidth,
        yGutters,
        hideXAxis,
        hideYAxis,
        resolvedYFormatter,
        labelToCoord,
    ])

    const drawStaticWithTicks = useMemo(() => {
        if (!tickMarkCoords) {
            return drawStatic
        }
        // Shared with the chart types' drawAxes calls, so ticks match their axis line.
        const tickColor = resolveAxisLineColor(theme)
        return (args: ChartDrawArgs): void => {
            drawStatic(args)
            drawTickMarks(args.ctx, args.dimensions, tickMarkCoords, tickColor)
        }
    }, [drawStatic, tickMarkCoords, theme])

    const { hoverIndex, hoverPosition, tooltipCtx, dragRect, handlers } = useChartInteraction<Meta>({
        scales,
        dimensions,
        labels,
        series: coloredSeries,
        canvasRef,
        wrapperRef,
        showTooltip,
        pinnable: pinnableTooltip,
        resolveClickToNearestSeries,
        onPointClick,
        onDateRangeZoom,
        resolveValue,
        resolvePositionValue,
        resolveBottomValue,
        interactionAxis,
        labelToCoord,
        wrapClickData,
    })

    // ref keeps composedDrawHover stable across drawHover identity changes
    const drawHoverRef = useLatest(drawHover)
    const composedDrawHover = useMemo(() => {
        const withCrosshair = composeDrawHoverWithCrosshair(() => drawHoverRef.current, {
            crosshairColor: theme.crosshairColor,
            crosshairDash: theme.crosshairDashPattern,
            showCrosshair,
            axisOrientation,
            labelToCoord,
        })
        return composeDrawHoverWithSelection(withCrosshair)
    }, [showCrosshair, theme.crosshairColor, theme.crosshairDashPattern, axisOrientation, labelToCoord, drawHoverRef.current])

    useChartDraw({
        ctx,
        overlayCtx,
        dimensions,
        scales,
        series: coloredSeries,
        labels,
        hoverIndex,
        hoverPosition,
        theme,
        dragRect,
        drawStatic: drawStaticWithTicks,
        drawHover: composedDrawHover,
        hoverAnimationMs,
    })

    const ariaLabel = useMemo(() => {
        const parts = [`Chart with ${countVisibleSeries(coloredSeries)} data series`]
        const cleanXAxisLabel = normalizeAxisLabel(xAxisLabel)
        const cleanYAxisLabel = normalizeAxisLabel(yAxisLabel)
        if (!hideXAxis && cleanXAxisLabel) {
            parts.push(`X-axis: ${cleanXAxisLabel}`)
        }
        if (!hideYAxis && cleanYAxisLabel) {
            parts.push(`Y-axis: ${cleanYAxisLabel}`)
        }
        return parts.join('. ')
    }, [coloredSeries, hideXAxis, hideYAxis, xAxisLabel, yAxisLabel])

    const canvasBounds = useCanvasBounds(canvasRef)

    // Overlays (value labels) anchor at the stacked top, so expose the position resolver —
    // falling back to the value resolver when the chart doesn't stack.
    const stablePositionValue = useStableResolveValue(resolvePositionValue ?? resolveValue)

    const axisValue = useMemo(
        () => ({ orientation: axisOrientation, xTickFormatter, isPercent }),
        [axisOrientation, xTickFormatter, isPercent]
    )
    const axisColor = theme.axisColor ?? DEFAULT_AXIS_COLOR

    const layoutValue = useMemo<ChartLayoutContextValue | null>(() => {
        if (!scales || !dimensions) {
            return null
        }
        return {
            scales,
            dimensions,
            labels,
            series: coloredSeries,
            theme,
            resolvePositionValue: stablePositionValue,
            canvasBounds,
            axis: axisValue,
            yGutters,
        }
    }, [scales, dimensions, labels, coloredSeries, theme, stablePositionValue, canvasBounds, axisValue, yGutters])

    const hoverValue = useMemo<ChartHoverContextValue>(() => ({ hoverIndex }), [hoverIndex])

    return (
        <ChartLayoutContext.Provider value={layoutValue}>
            <ChartHoverContext.Provider value={hoverValue}>
                <ChartShell
                    wrapperRef={wrapperRef}
                    canvasRef={canvasRef}
                    overlayCanvasRef={overlayCanvasRef}
                    className={className}
                    dataAttr={dataAttr}
                    pointer={hoverIndex >= 0 && !!onPointClick}
                    crosshair={!!onDateRangeZoom}
                    ariaLabel={ariaLabel}
                    handlers={handlers}
                    showOverlay={!!(dimensions && scales)}
                >
                    <AxisLabels
                        xTickFormatter={xTickFormatter}
                        yTickFormatter={resolvedYFormatter}
                        hideXAxis={hideXAxis}
                        hideYAxis={hideYAxis}
                        axisColor={axisColor}
                        orientation={axisOrientation}
                        labelToCoord={labelToCoord}
                        maxCategoryLabelWidth={maxCategoryLabelWidth}
                    />
                    <AxisTitles
                        xAxisLabel={xAxisLabel}
                        yAxisLabel={yAxisLabel}
                        hideXAxis={hideXAxis}
                        hideYAxis={hideYAxis}
                        orientation={axisOrientation}
                        axisColor={axisColor}
                    />

                    {children}

                    {tooltipCtx && showTooltip && (
                        <Tooltip context={tooltipCtx} renderTooltip={renderTooltip} placement={tooltipPlacement} />
                    )}
                </ChartShell>
            </ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
