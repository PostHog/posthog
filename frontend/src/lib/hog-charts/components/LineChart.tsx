import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { getSeriesColor } from 'lib/colors'

import { drawArea, drawGrid, drawHighlightPoint, drawLine, drawPoints } from '../core/canvas-renderer'
import type { DrawContext } from '../core/canvas-renderer'
import { buildPointClickData, buildTooltipContext, findNearestIndex, isInPlotArea } from '../core/interaction'
import { autoFormatYTick, computePercentStackData, createScales, type ScaleSet } from '../core/scales'
import type { ChartMargins, GoalLine, PointClickData, Series, TooltipContext } from '../core/types'
import { useChartCanvas } from '../core/use-chart-canvas'
import { AxisLabels } from '../overlays/AxisLabels'
import { Crosshair } from '../overlays/Crosshair'
import { DataLabels } from '../overlays/DataLabels'
import { GoalLines } from '../overlays/GoalLines'
import { Tooltip } from '../overlays/Tooltip'
import { TrendLine } from '../overlays/TrendLine'
import { ZoomBrush } from '../overlays/ZoomBrush'

export interface LineChartProps {
    // Data
    series: Series[]
    labels: string[]

    // Scale
    yScaleType?: 'linear' | 'log'
    multipleYAxes?: boolean
    percentStackView?: boolean

    // Axis formatting
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string

    // Tooltip (render prop)
    renderTooltip?: (context: TooltipContext) => React.ReactNode
    onTooltipShow?: (context: TooltipContext) => void
    onTooltipHide?: () => void

    // Interaction
    onPointClick?: (data: PointClickData) => void
    onRangeSelect?: (startIndex: number, endIndex: number) => void

    // Overlays
    showGrid?: boolean
    showCrosshair?: boolean
    showDataLabels?: boolean
    dataLabelFormatter?: (value: number, seriesIndex: number) => string
    showTrendLines?: boolean
    goalLines?: GoalLine[]

    // Incomplete data
    incompleteFromIndex?: number

    // Visibility
    hideXAxis?: boolean
    hideYAxis?: boolean

    // Styling
    className?: string
}

const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

export function LineChart({
    series,
    labels,
    yScaleType = 'linear',
    multipleYAxes = false,
    percentStackView = false,
    xTickFormatter,
    yTickFormatter,
    renderTooltip,
    onTooltipShow,
    onTooltipHide,
    onPointClick,
    onRangeSelect,
    showGrid = false,
    showCrosshair = false,
    showDataLabels = false,
    dataLabelFormatter,
    showTrendLines = false,
    goalLines,
    incompleteFromIndex,
    hideXAxis = false,
    hideYAxis = false,
    className,
}: LineChartProps): React.ReactElement {
    const theme = useMemo(() => buildTheme(), [])

    // Compute margins based on axis visibility
    const margins = useMemo<ChartMargins>(() => {
        const m = { ...DEFAULT_MARGINS }
        if (hideXAxis) {
            m.bottom = 8
        }
        if (hideYAxis) {
            m.left = 8
        }
        if (multipleYAxes) {
            m.right = 48
        }
        return m
    }, [hideXAxis, hideYAxis, multipleYAxes])

    const { canvasRef, wrapperRef, dimensions, ctx } = useChartCanvas({ margins })

    // Assign fallback colors to series
    const coloredSeries = useMemo(
        () =>
            series.map((s, i) => ({
                ...s,
                color: s.color || getSeriesColor(i),
            })),
        [series]
    )

    // Compute scales
    const scales = useMemo<ScaleSet | null>(() => {
        if (!dimensions) {
            return null
        }
        return createScales(coloredSeries, labels, dimensions, {
            scaleType: yScaleType,
            percentStack: percentStackView,
            multipleYAxes,
        })
    }, [coloredSeries, labels, dimensions, yScaleType, percentStackView, multipleYAxes])

    // Compute percent-stacked data
    const stackedData = useMemo(() => {
        if (!percentStackView) {
            return undefined
        }
        return computePercentStackData(coloredSeries, labels)
    }, [percentStackView, coloredSeries, labels])

    // Default Y tick formatter with auto-precision
    const resolvedYFormatter = useMemo(() => {
        if (yTickFormatter) {
            return yTickFormatter
        }
        if (percentStackView) {
            return (v: number) => `${Math.round(v * 100)}%`
        }
        const domain = scales?.y.domain() ?? [0, 1]
        const domainMax = Math.abs(domain[1])
        return (v: number) => autoFormatYTick(v, domainMax)
    }, [yTickFormatter, percentStackView, scales])

    // Hover state
    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [tooltipCtx, setTooltipCtx] = useState<TooltipContext | null>(null)

    // Zoom brush state
    const [brushStart, setBrushStart] = useState<{ x: number; index: number } | null>(null)
    const [brushCurrent, setBrushCurrent] = useState<number | null>(null)
    const isDragging = useRef(false)

    // Mouse handlers
    const handleMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!scales || !dimensions) {
                return
            }

            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top

            if (isDragging.current) {
                setBrushCurrent(mouseX)
                return
            }

            if (!isInPlotArea(mouseX, mouseY, dimensions)) {
                setHoverIndex(-1)
                if (tooltipCtx) {
                    setTooltipCtx(null)
                    onTooltipHide?.()
                }
                return
            }

            const index = findNearestIndex(mouseX, labels, (l) => scales.x(l))
            setHoverIndex(index)

            if (index >= 0 && renderTooltip) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                const ctx = buildTooltipContext(
                    index,
                    coloredSeries,
                    labels,
                    (l) => scales.x(l),
                    (v) => scales.y(v),
                    canvasBounds,
                    stackedData
                )
                setTooltipCtx(ctx)
                if (ctx) {
                    onTooltipShow?.(ctx)
                }
            }
        },
        [
            scales,
            dimensions,
            labels,
            coloredSeries,
            renderTooltip,
            stackedData,
            onTooltipShow,
            onTooltipHide,
            tooltipCtx,
            canvasRef,
        ]
    )

    const handleMouseLeave = useCallback(() => {
        if (!isDragging.current) {
            setHoverIndex(-1)
            setTooltipCtx(null)
            onTooltipHide?.()
        }
    }, [onTooltipHide])

    const handleMouseDown = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!scales || !dimensions || !onRangeSelect) {
                return
            }
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top

            if (!isInPlotArea(mouseX, mouseY, dimensions)) {
                return
            }

            const index = findNearestIndex(mouseX, labels, (l) => scales.x(l))
            isDragging.current = true
            setBrushStart({ x: mouseX, index })
            setBrushCurrent(mouseX)
            setTooltipCtx(null)
        },
        [scales, dimensions, labels, onRangeSelect]
    )

    const handleMouseUp = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!isDragging.current || !brushStart || !scales) {
                // Regular click
                if (onPointClick && hoverIndex >= 0) {
                    const clickData = buildPointClickData(hoverIndex, coloredSeries, labels, stackedData)
                    if (clickData) {
                        onPointClick(clickData)
                    }
                }
                return
            }

            isDragging.current = false

            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const endIndex = findNearestIndex(mouseX, labels, (l) => scales.x(l))

            if (endIndex >= 0 && endIndex !== brushStart.index) {
                const startIdx = Math.min(brushStart.index, endIndex)
                const endIdx = Math.max(brushStart.index, endIndex)
                onRangeSelect?.(startIdx, endIdx)
            }

            setBrushStart(null)
            setBrushCurrent(null)
        },
        [brushStart, scales, labels, onPointClick, onRangeSelect, hoverIndex, coloredSeries, stackedData]
    )

    const handleClick = useCallback(() => {
        if (isDragging.current) {
            return
        }
        if (onPointClick && hoverIndex >= 0) {
            const clickData = buildPointClickData(hoverIndex, coloredSeries, labels, stackedData)
            if (clickData) {
                onPointClick(clickData)
            }
        }
    }, [onPointClick, hoverIndex, coloredSeries, labels, stackedData])

    // Canvas rendering
    useEffect(() => {
        if (!ctx || !dimensions || !scales) {
            return
        }

        const dpr = window.devicePixelRatio || 1
        ctx.save()
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, dimensions.width, dimensions.height)

        const drawCtx: DrawContext = {
            ctx,
            dimensions,
            xScale: scales.x,
            yScale: scales.y,
            labels,
        }

        // Grid
        if (showGrid) {
            drawGrid(drawCtx, {
                gridColor: theme.gridColor,
                goalLineValues: goalLines?.map((g) => g.value),
            })
        }

        // Series
        for (const s of coloredSeries) {
            if (s.hidden) {
                continue
            }

            const yScale =
                multipleYAxes && s.yAxisId && scales.yAxes.has(s.yAxisId) ? scales.yAxes.get(s.yAxisId)! : scales.y

            const seriesDrawCtx: DrawContext = { ...drawCtx, yScale }
            const yValues = stackedData?.get(s.key)

            // Area fill
            if (s.fillArea) {
                drawArea(seriesDrawCtx, s, yValues, { incompleteFromIndex })
            }

            // Line
            drawLine(seriesDrawCtx, s, yValues, { incompleteFromIndex })

            // Points
            drawPoints(seriesDrawCtx, s, yValues)
        }

        // Hover highlight points
        if (hoverIndex >= 0) {
            for (const s of coloredSeries) {
                if (s.hidden) {
                    continue
                }
                const data = stackedData?.get(s.key) ?? s.data
                const x = scales.x(labels[hoverIndex])
                const yScale =
                    multipleYAxes && s.yAxisId && scales.yAxes.has(s.yAxisId) ? scales.yAxes.get(s.yAxisId)! : scales.y
                const y = yScale(data[hoverIndex])
                if (x != null && isFinite(y)) {
                    drawHighlightPoint(ctx, x, y, s.color)
                }
            }
        }

        ctx.restore()
    }, [
        ctx,
        dimensions,
        scales,
        coloredSeries,
        labels,
        showGrid,
        theme,
        goalLines,
        stackedData,
        incompleteFromIndex,
        hoverIndex,
        multipleYAxes,
    ])

    // Cursor style
    const cursorStyle = hoverIndex >= 0 && onPointClick ? 'pointer' : 'default'

    return (
        <div
            ref={wrapperRef as React.RefObject<HTMLDivElement>}
            className={className}
            style={{ position: 'relative', width: '100%', flex: 1, minHeight: 0, cursor: cursorStyle }}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            onMouseDown={handleMouseDown}
            onMouseUp={handleMouseUp}
            onClick={handleClick}
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

            {/* Overlay layer */}
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
                {dimensions && scales && (
                    <>
                        {/* Axis labels */}
                        <AxisLabels
                            dimensions={dimensions}
                            xScale={scales.x}
                            yScale={scales.y}
                            labels={labels}
                            xTickFormatter={xTickFormatter}
                            yTickFormatter={resolvedYFormatter}
                            hideXAxis={hideXAxis}
                            hideYAxis={hideYAxis}
                            axisColor={theme.axisColor}
                        />

                        {/* Right-side Y axes for multi-axis */}
                        {multipleYAxes &&
                            Array.from(scales.yAxes.entries()).map(([axisId, yScale], i) => {
                                if (axisId === 'y') {
                                    return null
                                }
                                return (
                                    <AxisLabels
                                        key={axisId}
                                        dimensions={dimensions}
                                        xScale={scales.x}
                                        yScale={yScale}
                                        labels={labels}
                                        yTickFormatter={resolvedYFormatter}
                                        hideXAxis
                                        axisColor={theme.axisColor}
                                        yAxisSide={i % 2 === 0 ? 'right' : 'left'}
                                    />
                                )
                            })}

                        {/* Crosshair */}
                        {showCrosshair &&
                            hoverIndex >= 0 &&
                            !isDragging.current &&
                            (() => {
                                const x = scales.x(labels[hoverIndex])
                                return x != null ? (
                                    <Crosshair x={x} dimensions={dimensions} color={theme.crosshairColor} />
                                ) : null
                            })()}

                        {/* Goal lines */}
                        {goalLines && goalLines.length > 0 && (
                            <GoalLines goalLines={goalLines} yScale={(v) => scales.y(v)} dimensions={dimensions} />
                        )}

                        {/* Data labels */}
                        {showDataLabels && (
                            <DataLabels
                                series={coloredSeries}
                                labels={labels}
                                xScale={scales.x}
                                yScale={scales.y}
                                dimensions={dimensions}
                                formatter={dataLabelFormatter}
                                stackedData={stackedData}
                            />
                        )}

                        {/* Trend lines */}
                        {showTrendLines && (
                            <TrendLine
                                series={coloredSeries}
                                labels={labels}
                                xScale={scales.x}
                                yScale={scales.y}
                                dimensions={dimensions}
                                incompleteFromIndex={incompleteFromIndex}
                            />
                        )}

                        {/* Zoom brush */}
                        {brushStart && brushCurrent != null && (
                            <ZoomBrush startX={brushStart.x} currentX={brushCurrent} dimensions={dimensions} />
                        )}

                        {/* Tooltip */}
                        {tooltipCtx && renderTooltip && !isDragging.current && (
                            <Tooltip context={tooltipCtx} renderTooltip={renderTooltip} />
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
