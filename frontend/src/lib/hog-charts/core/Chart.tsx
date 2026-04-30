import * as d3 from 'd3'
import React, { useCallback, useMemo, useRef } from 'react'

import { AxisLabels, measureLabelWidth } from '../overlays/AxisLabels'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { drawCrosshair } from './canvas-renderer'
import { ChartHoverContext, ChartLayoutContext } from './chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from './chart-context'
import { ChartErrorBoundary } from './ChartErrorBoundary'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useChartInteraction } from './hooks/useChartInteraction'
import { autoFormatYTick, seriesValueRange } from './scales'
import { DEFAULT_Y_AXIS_ID } from './types'
import type {
    ChartConfig,
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

export const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

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

    const hasMultipleAxes = useMemo(() => {
        const axisIds = new Set(
            series.filter((s) => !s.visibility?.excluded).map((s) => s.yAxisId ?? DEFAULT_Y_AXIS_ID)
        )
        return axisIds.size > 1
    }, [series])

    const yLabelWidth = useMemo<number>(() => {
        if (hideYAxis) {
            return 0
        }
        const range = seriesValueRange(series)
        if (range.count === 0) {
            return 0
        }
        const min = range.min > 0 ? 0 : range.min
        const max = range.max < 0 ? 0 : range.max
        const ticks = d3.scaleLinear().domain([min, max]).nice(6).ticks(6)
        if (ticks.length === 0) {
            return 0
        }
        const domainMax = Math.max(...ticks.map((t) => Math.abs(t)))
        const formatter = yTickFormatter ?? ((v: number) => autoFormatYTick(v, domainMax))
        let widest = 0
        for (const t of ticks) {
            widest = Math.max(widest, measureLabelWidth(formatter(t)))
        }
        return widest
    }, [series, yTickFormatter, hideYAxis])

    const xLabelHalfWidth = useMemo<number>(() => {
        if (hideXAxis || labels.length === 0) {
            return 0
        }
        let widest = 0
        for (let i = 0; i < labels.length; i++) {
            const text = xTickFormatter ? xTickFormatter(labels[i], i) : labels[i]
            if (text === null) {
                continue
            }
            widest = Math.max(widest, measureLabelWidth(text))
        }
        return Math.ceil(widest / 2)
    }, [labels, xTickFormatter, hideXAxis])

    const margins = useMemo<ChartMargins>(() => {
        const m = { ...DEFAULT_MARGINS }
        if (hideXAxis) {
            m.bottom = 8
        }
        if (hideYAxis) {
            m.left = 8
        } else {
            m.left = Math.max(20, Math.ceil(yLabelWidth) + 12, xLabelHalfWidth + 4)
        }
        if (hasMultipleAxes && !hideYAxis) {
            m.right = Math.max(48, xLabelHalfWidth + 4)
        } else {
            m.right = Math.max(DEFAULT_MARGINS.right, xLabelHalfWidth + 4)
        }
        return m
    }, [hideXAxis, hideYAxis, hasMultipleAxes, yLabelWidth, xLabelHalfWidth])

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

    const resolvedYFormatter = useMemo(() => {
        if (yTickFormatter) {
            return yTickFormatter
        }
        const ticks = scales?.yTicks() ?? []
        const domainMax = ticks.length > 0 ? Math.abs(Math.max(...ticks)) : 1
        return (v: number) => autoFormatYTick(v, domainMax)
    }, [yTickFormatter, scales])

    const resolvedYRightFormatter = useMemo(() => {
        if (yTickFormatter) {
            return yTickFormatter
        }
        const rightAxis = scales?.yAxes && Object.values(scales.yAxes).find((a) => a.position === 'right')
        if (!rightAxis) {
            return undefined
        }
        const ticks = rightAxis.ticks()
        const domainMax = ticks.length > 0 ? Math.abs(Math.max(...ticks)) : 1
        return (v: number) => autoFormatYTick(v, domainMax)
    }, [yTickFormatter, scales])

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

    // Compose the chart-type's drawHover with a crosshair pass so per-mousemove
    // hover indication stays entirely on the canvas — DOM-based overlays would
    // force per-event style invalidation/layout that scales badly with chart
    // content size. Crosshair drawn first so highlight rings render on top.
    //
    // drawHover is held via a ref so composedDrawHover stays referentially stable
    // even when the parent recreates drawHover (e.g. stackedData changes). Without
    // this, useChartDraw's hover effect re-fires on every drawHover identity change,
    // and the resulting requestAnimationFrame churn can race with tooltip rendering.
    const drawHoverRef = useRef(drawHover)
    drawHoverRef.current = drawHover
    const composedDrawHover = useCallback(
        (args: ChartDrawArgs) => {
            if (showCrosshair && theme.crosshairColor && args.hoverIndex >= 0) {
                const x = args.scales.x(args.labels[args.hoverIndex])
                if (x != null && isFinite(x)) {
                    drawCrosshair(args.ctx, args.dimensions, x, theme.crosshairColor)
                }
            }
            drawHoverRef.current(args)
        },
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

    // Wrap resolveValue in a ref + stable callback so callers don't have to memoize it.
    // An un-memoized arrow literal from a parent would otherwise invalidate the layout
    // context on every render and defeat the layout/hover split.
    //
    // The ref is written during render rather than via an effect because overlays read
    // it during their render via `useChartLayout().resolveValue`; deferring the write
    // would expose them to last-commit's value. This is safe under StrictMode/concurrent
    // rendering: an aborted render that wrote the ref will be re-driven with the same
    // props, so the kept render observes an idempotent state.
    const resolveValueRef = useRef<ResolveValueFn | undefined>(resolveValue)
    resolveValueRef.current = resolveValue
    const stableResolveValue = useCallback<ResolveValueFn>((s, i) => {
        const fn = resolveValueRef.current
        if (fn) {
            return fn(s, i)
        }
        const v = s.data[i]
        return typeof v === 'number' && Number.isFinite(v) ? v : 0
    }, [])

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
        <ChartErrorBoundary>
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
        </ChartErrorBoundary>
    )
}
