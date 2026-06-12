import React, { useMemo } from 'react'

import { AxisLabels } from '../overlays/AxisLabels'
import { AxisTitles } from '../overlays/AxisTitles'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { normalizeAxisLabel } from '../utils/axis-labels'
import { composeDrawHoverWithCrosshair } from './canvas-renderer'
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
import type {
    ChartConfig,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    DrawHoverResult,
    PointClickData,
    ResolveValueFn,
    Series,
    TooltipContext,
} from './types'

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
    tooltip: renderTooltip = DefaultTooltip,
    onPointClick,
    className,
    dataAttr,
    children,
    resolveValue,
    resolvePositionValue,
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
        axisOrientation = 'vertical',
        isPercent = false,
        animateHover,
        margins: marginsOverride,
        maxCategoryLabelWidth,
    } = config ?? {}
    const hoverAnimationMs = resolveHoverAnimationMs(animateHover)
    const interactionAxis: 'x' | 'y' = axisOrientation === 'horizontal' ? 'y' : 'x'
    const {
        enabled: showTooltip = true,
        pinnable: pinnableTooltip = false,
        placement: tooltipPlacement = 'follow-data',
    } = tooltipConfig ?? {}

    const margins = useChartMargins({
        series,
        labels,
        hideXAxis,
        hideYAxis,
        xAxisLabel,
        yAxisLabel,
        xTickFormatter,
        yTickFormatter,
        axisOrientation,
        override: marginsOverride,
        valueRangeSeries,
        maxCategoryLabelWidth,
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

    const { hoverIndex, hoverPosition, tooltipCtx, handlers } = useChartInteraction<Meta>({
        scales,
        dimensions,
        labels,
        series: coloredSeries,
        canvasRef,
        wrapperRef,
        showTooltip,
        pinnable: pinnableTooltip,
        onPointClick,
        resolveValue,
        resolvePositionValue,
        interactionAxis,
        labelToCoord,
        wrapClickData,
    })

    // ref keeps composedDrawHover stable across drawHover identity changes
    const drawHoverRef = useLatest(drawHover)
    const composedDrawHover = useMemo(
        () =>
            composeDrawHoverWithCrosshair(() => drawHoverRef.current, {
                crosshairColor: theme.crosshairColor,
                showCrosshair,
                axisOrientation,
                labelToCoord,
            }),
        [showCrosshair, theme.crosshairColor, axisOrientation, labelToCoord, drawHoverRef.current]
    )

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
        drawStatic,
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
        }
    }, [scales, dimensions, labels, coloredSeries, theme, stablePositionValue, canvasBounds, axisValue])

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
                    ariaLabel={ariaLabel}
                    handlers={handlers}
                    showOverlay={!!(dimensions && scales)}
                >
                    <AxisLabels
                        xTickFormatter={xTickFormatter}
                        yTickFormatter={resolvedYFormatter}
                        userYTickFormatter={yTickFormatter}
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
