import React, { useCallback, useMemo } from 'react'

import { AxisLabels } from '../overlays/AxisLabels'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { composeDrawHoverWithCrosshair } from './canvas-renderer'
import { ChartHoverContext, ChartLayoutContext } from './chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from './chart-context'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useChartInteraction } from './hooks/useChartInteraction'
import { useChartMargins } from './hooks/useChartMargins'
import { useLatest } from './hooks/useLatest'
import { useResolvedYFormatters } from './hooks/useResolvedYFormatters'
import { useStableResolveValue } from './hooks/useStableResolveValue'
import type {
    ChartConfig,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
    TooltipContext,
} from './types'

const OVERLAY_STYLE: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    pointerEvents: 'none',
}

const WRAPPER_STYLE_BASE: React.CSSProperties = {
    position: 'relative',
    width: '100%',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
}
const WRAPPER_STYLE_DEFAULT: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'default' }
const WRAPPER_STYLE_POINTER: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'pointer' }

const STATIC_CANVAS_STYLE: React.CSSProperties = { position: 'absolute', top: 0, left: 0 }
const OVERLAY_CANVAS_STYLE: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    pointerEvents: 'none',
}

function OverlayLayer({ children }: { children: React.ReactNode }): React.ReactElement {
    return <div style={OVERLAY_STYLE}>{children}</div>
}

export interface ChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: ChartConfig
    theme: ChartTheme
    createScales: CreateScalesFn
    /** Static layer — grid, lines, areas, points. Redrawn only when chart inputs change. */
    drawStatic: (args: ChartDrawArgs) => void
    /** Hover overlay — highlight rings only. Redrawn on every hoverIndex change. */
    drawHover: (args: ChartDrawArgs) => void
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    children?: React.ReactNode
    /** Resolves the y-value for a series at a given index. Defaults to series.data[index].
     *  Identity is read live for tooltip values and overlays, but the pinned-tooltip
     *  rebuild only refires when `series`, `labels`, or `scales` change. Callers that
     *  derive values from data not reflected in those (e.g. an external "%" toggle)
     *  should ensure that toggle also updates `series` or the chart's scales — otherwise
     *  a held pin will keep showing values from the previous resolver. */
    resolveValue?: ResolveValueFn
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
    children,
    resolveValue,
}: ChartProps<Meta>): React.ReactElement {
    const {
        xTickFormatter,
        yTickFormatter,
        hideXAxis = false,
        hideYAxis = false,
        tooltip: tooltipConfig,
        showCrosshair = false,
    } = config ?? {}
    const {
        enabled: showTooltip = true,
        pinnable: pinnableTooltip = false,
        placement: tooltipPlacement = 'follow-data',
    } = tooltipConfig ?? {}

    const margins = useChartMargins({ series, labels, hideXAxis, hideYAxis, xTickFormatter, yTickFormatter })

    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({ margins })

    const coloredSeries = useMemo<ResolvedSeries<Meta>[]>(
        () =>
            series.map((s, i) => ({
                ...s,
                color: s.color || theme.colors[i % theme.colors.length],
            })),
        [series, theme.colors]
    )

    const scales = useMemo<ChartScales | null>(() => {
        if (!dimensions) {
            return null
        }
        return createScalesFn(coloredSeries, labels, dimensions)
    }, [coloredSeries, labels, dimensions, createScalesFn])

    const { left: resolvedYFormatter, right: resolvedYRightFormatter } = useResolvedYFormatters(scales, yTickFormatter)

    const { hoverIndex, tooltipCtx, handlers } = useChartInteraction<Meta>({
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
    })

    // ref keeps composedDrawHover stable across drawHover identity changes
    const drawHoverRef = useLatest(drawHover)
    const composedDrawHover = useMemo(
        () => composeDrawHoverWithCrosshair(() => drawHoverRef.current, theme.crosshairColor, showCrosshair),
        [showCrosshair, theme.crosshairColor]
    )

    useChartDraw({
        ctx,
        overlayCtx,
        dimensions,
        scales,
        series: coloredSeries,
        labels,
        hoverIndex,
        theme,
        drawStatic,
        drawHover: composedDrawHover,
    })

    const wrapperStyle = hoverIndex >= 0 && onPointClick ? WRAPPER_STYLE_POINTER : WRAPPER_STYLE_DEFAULT

    const ariaLabel = useMemo(() => {
        const visible = coloredSeries.reduce((n, s) => n + (s.visibility?.excluded ? 0 : 1), 0)
        return `Chart with ${visible} data series`
    }, [coloredSeries])

    const canvasBounds = useCallback(
        (): DOMRect | null => canvasRef.current?.getBoundingClientRect() ?? null,
        [canvasRef]
    )

    const stableResolveValue = useStableResolveValue(resolveValue)

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
            resolveValue: stableResolveValue,
            canvasBounds,
        }
    }, [scales, dimensions, labels, coloredSeries, theme, stableResolveValue, canvasBounds])

    const hoverValue = useMemo<ChartHoverContextValue>(() => ({ hoverIndex }), [hoverIndex])

    return (
        <ChartLayoutContext.Provider value={layoutValue}>
            <ChartHoverContext.Provider value={hoverValue}>
                <div
                    ref={wrapperRef}
                    className={className}
                    style={wrapperStyle}
                    onMouseMove={handlers.onMouseMove}
                    onMouseLeave={handlers.onMouseLeave}
                    onClick={handlers.onClick}
                >
                    <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={STATIC_CANVAS_STYLE} />
                    <canvas ref={overlayCanvasRef} aria-hidden="true" style={OVERLAY_CANVAS_STYLE} />

                    {dimensions && scales && (
                        <OverlayLayer>
                            <AxisLabels
                                xTickFormatter={xTickFormatter}
                                yTickFormatter={resolvedYFormatter}
                                yRightTickFormatter={resolvedYRightFormatter}
                                hideXAxis={hideXAxis}
                                hideYAxis={hideYAxis}
                                axisColor={theme.axisColor}
                            />

                            {children}

                            {tooltipCtx && showTooltip && (
                                <Tooltip
                                    context={tooltipCtx}
                                    renderTooltip={renderTooltip}
                                    placement={tooltipPlacement}
                                />
                            )}
                        </OverlayLayer>
                    )}
                </div>
            </ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
