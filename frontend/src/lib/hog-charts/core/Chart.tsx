import React, { useCallback, useMemo, useRef } from 'react'

import { AxisLabels } from '../overlays/AxisLabels'
import { Crosshair } from '../overlays/Crosshair'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { ChartHoverContext, ChartLayoutContext } from './chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from './chart-context'
import { ChartErrorBoundary } from './ChartErrorBoundary'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useChartInteraction } from './hooks/useChartInteraction'
import { autoFormatYTick } from './scales'
import { DEFAULT_Y_AXIS_ID } from './types'
import type {
    ChartConfig,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
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

function OverlayLayer({ children }: { children: React.ReactNode }): React.ReactElement {
    return <div style={OVERLAY_STYLE}>{children}</div>
}

export interface ChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: ChartConfig
    theme: ChartTheme
    createScales: CreateScalesFn
    draw: (args: ChartDrawArgs) => void
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    children?: React.ReactNode
    /** Resolves the y-value for a series at a given index. Defaults to series.data[index]. */
    resolveValue?: ResolveValueFn
}

export const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

export function Chart<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    createScales: createScalesFn,
    draw,
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
        showTooltip = true,
        pinnableTooltip = false,
        showCrosshair = false,
    } = config ?? {}

    const hasMultipleAxes = useMemo(() => {
        const axisIds = new Set(
            series.filter((s) => !s.visibility?.excluded).map((s) => s.yAxisId ?? DEFAULT_Y_AXIS_ID)
        )
        return axisIds.size > 1
    }, [series])

    const margins = useMemo<ChartMargins>(() => {
        const m = { ...DEFAULT_MARGINS }
        if (hideXAxis) {
            m.bottom = 8
        }
        if (hideYAxis) {
            m.left = 8
        }
        if (hasMultipleAxes && !hideYAxis) {
            m.right = 48
        }
        return m
    }, [hideXAxis, hideYAxis, hasMultipleAxes])

    const { canvasRef, wrapperRef, dimensions, ctx } = useChartCanvas({ margins })

    const coloredSeries = useMemo(
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

    useChartDraw({
        ctx,
        dimensions,
        scales,
        series: coloredSeries,
        labels,
        hoverIndex,
        theme,
        draw,
    })

    const cursorStyle = hoverIndex >= 0 && onPointClick ? 'pointer' : 'default'

    const canvasBounds = useCallback(
        (): DOMRect | null => canvasRef.current?.getBoundingClientRect() ?? null,
        [canvasRef]
    )

    // Wrap resolveValue in a ref + stable callback so callers don't have to memoize it.
    // An un-memoized arrow literal from a parent would otherwise invalidate the layout
    // context on every render and defeat the layout/hover split.
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
                        style={{ position: 'relative', width: '100%', flex: 1, minHeight: 0, cursor: cursorStyle }}
                        onMouseMove={handlers.onMouseMove}
                        onMouseLeave={handlers.onMouseLeave}
                        onClick={handlers.onClick}
                    >
                        <canvas
                            ref={canvasRef}
                            role="img"
                            aria-label={`Chart with ${coloredSeries.reduce((n, s) => n + (s.visibility?.excluded ? 0 : 1), 0)} data series`}
                            style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                cursor: cursorStyle,
                            }}
                        />

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

                                {showCrosshair && <Crosshair color={theme.crosshairColor} />}

                                {children}

                                {tooltipCtx && showTooltip && (
                                    <Tooltip context={tooltipCtx} renderTooltip={renderTooltip} />
                                )}
                            </OverlayLayer>
                        )}
                    </div>
                </ChartHoverContext.Provider>
            </ChartLayoutContext.Provider>
        </ChartErrorBoundary>
    )
}
