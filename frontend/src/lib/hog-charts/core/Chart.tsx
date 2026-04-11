import React, { useMemo } from 'react'

import { AxisLabels } from '../overlays/AxisLabels'
import { Crosshair } from '../overlays/Crosshair'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { GoalLines } from '../overlays/GoalLines'
import { Tooltip } from '../overlays/Tooltip'
import { ChartContext } from './chart-context'
import { ChartErrorBoundary } from './ChartErrorBoundary'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useChartInteraction } from './hooks/useChartInteraction'
import { autoFormatYTick } from './scales'
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

export interface ChartProps {
    series: Series[]
    labels: string[]
    config?: ChartConfig
    theme: ChartTheme
    createScales: CreateScalesFn
    draw: (args: ChartDrawArgs) => void
    tooltip?: (ctx: TooltipContext) => React.ReactNode
    onPointClick?: (data: PointClickData) => void
    className?: string
    children?: React.ReactNode
    /** Resolves the y-value for a series at a given index. Defaults to series.data[index]. */
    resolveValue?: ResolveValueFn
}

export const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

export function Chart({
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
}: ChartProps): React.ReactElement {
    const {
        xTickFormatter,
        yTickFormatter,
        hideXAxis = false,
        hideYAxis = false,
        showTooltip = true,
        pinnableTooltip = false,
        showCrosshair = false,
        goalLines,
    } = config ?? {}

    const margins = useMemo<ChartMargins>(() => {
        const m = { ...DEFAULT_MARGINS }
        if (hideXAxis) {
            m.bottom = 8
        }
        if (hideYAxis) {
            m.left = 8
        }
        return m
    }, [hideXAxis, hideYAxis])

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

    const { hoverIndex, tooltipCtx, handlers } = useChartInteraction({
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

    const contextValue = useMemo(() => {
        if (!scales || !dimensions) {
            return null
        }
        return {
            scales,
            dimensions,
            labels,
            series: coloredSeries,
            hoverIndex,
        }
    }, [scales, dimensions, labels, coloredSeries, hoverIndex])

    return (
        <ChartErrorBoundary>
            <ChartContext.Provider value={contextValue}>
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
                        aria-label={`Chart with ${coloredSeries.reduce((n, s) => n + (s.hidden ? 0 : 1), 0)} data series`}
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
                                hideXAxis={hideXAxis}
                                hideYAxis={hideYAxis}
                                axisColor={theme.axisColor}
                            />

                            {showCrosshair && <Crosshair color={theme.crosshairColor} />}

                            {goalLines && goalLines.length > 0 && <GoalLines goalLines={goalLines} />}

                            {tooltipCtx && showTooltip && (
                                <Tooltip context={tooltipCtx} renderTooltip={renderTooltip} />
                            )}

                            {children}
                        </OverlayLayer>
                    )}
                </div>
            </ChartContext.Provider>
        </ChartErrorBoundary>
    )
}
