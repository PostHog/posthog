import React, { useMemo, useEffect } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { getSeriesColor } from 'lib/colors'

import { AxisLabels } from '../overlays/AxisLabels'
import { Crosshair } from '../overlays/Crosshair'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { GoalLines } from '../overlays/GoalLines'
import { Tooltip } from '../overlays/Tooltip'
import { ChartContext } from './chart-context'
import { autoFormatYTick } from './scales'
import type {
    ChartConfig,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    CreateScalesFn,
    PointClickData,
    Series,
    TooltipContext,
} from './types'
import { useChartCanvas } from './use-chart-canvas'
import { useChartInteraction } from './use-chart-interaction'

function OverlayLayer({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <div
            style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
            }}
        >
            {children}
        </div>
    )
}

export interface ChartProps {
    series: Series[]
    labels: string[]
    config?: ChartConfig
    createScales: CreateScalesFn
    draw: (args: ChartDrawArgs) => void
    tooltip?: React.ComponentType<TooltipContext>
    onPointClick?: (data: PointClickData) => void
    className?: string
    children?: React.ReactNode
    stackedData?: Map<string, number[]>
}

const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

export function Chart({
    series,
    labels,
    config,
    createScales: createScalesFn,
    draw,
    tooltip: TooltipComponent = DefaultTooltip,
    onPointClick,
    className,
    children,
    stackedData,
}: ChartProps): React.ReactElement {
    const {
        xTickFormatter,
        yTickFormatter,
        hideXAxis = false,
        hideYAxis = false,
        showTooltip = true,
        showCrosshair = false,
        goalLines,
    } = config ?? {}

    const theme = useMemo(() => buildTheme(), [])

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
                color: s.color || getSeriesColor(i),
            })),
        [series]
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
        const domain = scales?.yRaw.domain() ?? [0, 1]
        const domainMax = Math.abs(domain[1])
        return (v: number) => autoFormatYTick(v, domainMax)
    }, [yTickFormatter, scales])

    const { hoverIndex, tooltipCtx, handlers } = useChartInteraction({
        scales,
        dimensions,
        labels,
        series: coloredSeries,
        canvasRef,
        showTooltip,
        onPointClick,
        stackedData,
    })

    useEffect(() => {
        if (!ctx || !dimensions || !scales) {
            return
        }

        const dpr = window.devicePixelRatio || 1
        ctx.save()
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, dimensions.width, dimensions.height)

        draw({
            ctx,
            dimensions,
            scales,
            series: coloredSeries,
            labels,
            hoverIndex,
            theme,
        })

        ctx.restore()
    }, [ctx, dimensions, scales, coloredSeries, labels, theme, hoverIndex, draw])

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
        <ChartContext.Provider value={contextValue}>
            <div
                ref={wrapperRef as React.RefObject<HTMLDivElement>}
                className={className}
                style={{ position: 'relative', width: '100%', flex: 1, minHeight: 0, cursor: cursorStyle }}
                onMouseMove={handlers.onMouseMove}
                onMouseLeave={handlers.onMouseLeave}
                onClick={handlers.onClick}
            >
                <canvas
                    ref={canvasRef as React.RefObject<HTMLCanvasElement>}
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

                        {tooltipCtx && showTooltip && <Tooltip context={tooltipCtx} component={TooltipComponent} />}

                        {children}
                    </OverlayLayer>
                )}
            </div>
        </ChartContext.Provider>
    )
}
