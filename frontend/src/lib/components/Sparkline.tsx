import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Popover } from '@posthog/lemon-ui'

import { Chart, ChartItem, ScaleOptions, TooltipModel } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { humanFriendlyNumber } from 'lib/utils'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'

import { LemonSkeleton } from '../lemon-ui/LemonSkeleton'

export interface SparklineTimeSeries {
    name: string
    values: number[]
    /** Check vars.scss for available colors. @default 'muted' */
    color?: string
    hoverColor?: string
}

export type AnyScaleOptions = ScaleOptions<'linear' | 'logarithmic' | 'time' | 'timeseries' | 'category'>

interface SparklineProps {
    /** Either a list of numbers for a muted graph or an array of time series */
    data: number[] | SparklineTimeSeries[]
    /** Check vars.scss for available colors. @default 'muted' */
    color?: string
    colors?: string[]
    /** A name for each time series. */
    name?: string
    names?: string[]
    /** A label for each datapoint. */
    labels?: string[]
    /** @default 'bar' */
    type?: 'bar' | 'line'
    /** Whether the Y-axis maximum should be indicated in the graph. @default true */
    maximumIndicator?: boolean
    /** A skeleton is shown during loading. */
    loading?: boolean
    /** Update the X-axis scale. */
    withXScale?: (x: AnyScaleOptions) => AnyScaleOptions
    /** Update the Y-axis scale. */
    withYScale?: (y: AnyScaleOptions) => AnyScaleOptions
    /** Render a label for the tooltip. */
    renderLabel?: (label: string) => string
    /** Render a count for the tooltip. */
    renderCount?: (count: number) => React.ReactNode
    className?: string
    onSelectionChange?: (selection: { startIndex: number; endIndex: number }) => void
}

export function Sparkline({
    data,
    color,
    colors,
    name,
    names,
    labels,
    type = 'bar',
    maximumIndicator = true,
    loading = false,
    withXScale,
    withYScale,
    renderLabel,
    renderCount,
    onSelectionChange,
    className,
}: SparklineProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const tooltipRef = useRef<HTMLDivElement | null>(null)

    const [tooltip, setTooltip] = useState<TooltipModel<'bar'> | null>(null)
    const dragStartRef = useRef<{ index: number; x: number } | null>(null)
    const [isDragging, setIsDragging] = useState(false)

    const adjustedData: SparklineTimeSeries[] = useMemo(() => {
        const arrayData = Array.isArray(data)
            ? data.length > 0 && typeof data[0] === 'object'
                ? data // array of objects, one per series
                : [data] // array of numbers, turn it into the first series
            : typeof data === 'object'
              ? [data] // first series as an object
              : [[data]] // just a random number... huh
        return arrayData.map((timeseries, index): SparklineTimeSeries => {
            const defaultName =
                names?.[index] || (arrayData.length === 1 ? name || 'Count' : `${name || 'Series'} ${index + 1}`)
            const defaultColor = colors?.[index] || color || 'muted'
            if (typeof timeseries === 'object') {
                if (!Array.isArray(timeseries)) {
                    return {
                        name: timeseries.name || defaultName,
                        color: timeseries.color || defaultColor,
                        values: timeseries.values || [],
                    }
                }
                return {
                    name: defaultName,
                    color: defaultColor,
                    values: timeseries as number[],
                }
            }
            return {
                name: defaultName,
                color: defaultColor,
                values: timeseries ? [timeseries] : [],
            }
        })
    }, [data]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        // data should always be provided but React can render this without it,
        // so, fall back to an empty array for safety
        if (data === undefined || data.length === 0) {
            return
        }
        const defaultXScale: AnyScaleOptions = {
            // X axis not needed in line charts without indicators
            display: type === 'bar' || maximumIndicator,
            bounds: 'data',
            stacked: true,
            ticks: {
                display: false,
            },
            grid: {
                drawTicks: false,
                display: false,
            },
            alignToPixels: true,
        }

        const defaultYScale: AnyScaleOptions = {
            // We use the Y axis for the maximum indicator
            display: maximumIndicator,
            bounds: 'data',
            min: 0, // Always starting at 0
            suggestedMax: 1,
            stacked: true,
            ticks: {
                includeBounds: true,
                autoSkip: true,
                maxTicksLimit: 1, // Only the max
                align: 'start',
                callback: (tickValue) =>
                    typeof tickValue === 'number' && tickValue > 0 // Hide the zero tick
                        ? humanFriendlyNumber(tickValue)
                        : null,
                font: {
                    size: 10,
                    lineHeight: 1,
                },
            },
            grid: {
                tickBorderDash: [2],
                display: true,
                tickLength: 0,
            },
            border: { display: false },
            alignToPixels: true,
            afterFit: (axis) => {
                // Remove unnecessary padding
                axis.paddingTop = 1 // 1px and not 0 to avoid clipping of the grid
                axis.paddingBottom = 1
            },
        }

        let chart: Chart
        if (canvasRef.current) {
            const xScale = withXScale ? withXScale(defaultXScale) : defaultXScale
            const yScale = withYScale ? withYScale(defaultYScale) : defaultYScale
            chart = new Chart(canvasRef.current.getContext('2d') as ChartItem, {
                type,
                data: {
                    labels: labels || adjustedData[0].values.map((_, i) => `Entry ${i}`),
                    datasets: adjustedData.map((timeseries) => {
                        const color = getColorVar(timeseries.color || 'muted')
                        const hoverColor = getColorVar(timeseries.hoverColor || timeseries.color || 'muted')
                        return {
                            label: timeseries.name,
                            data: timeseries.values,
                            minBarLength: 0,
                            categoryPercentage: 0.9, // Slightly tighter bar spacing than the default 0.8
                            backgroundColor: color,
                            hoverBackgroundColor: hoverColor,
                            borderColor: color,
                            borderWidth: type === 'line' ? 2 : 0,
                            pointRadius: 0,
                            borderRadius: 2,
                        }
                    }),
                },
                options: {
                    scales: {
                        x: xScale,
                        y: yScale,
                    },
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            enabled: false, // Using external tooltip
                            external({ tooltip }) {
                                // We spread it otherwise it just ends up being a reference to the tooltip object
                                setTooltip({ ...tooltip } as TooltipModel<'bar'>)
                            },
                        },
                    },
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        axis: 'x',
                        intersect: false,
                    },
                },
            })
        }
        return () => {
            chart?.destroy()
        }
    }, [labels, adjustedData, withXScale, withYScale, renderLabel, data, maximumIndicator, type])

    const dataPointCount = adjustedData[0]?.values?.length || 0
    const finalClassName = clsx(
        dataPointCount > 16 ? 'w-64' : dataPointCount > 8 ? 'w-48' : dataPointCount > 4 ? 'w-32' : 'w-24',
        className
    )

    const tooltipVisible = !!(tooltip && tooltip.opacity > 0)
    const toolTipDataPoints = tooltip && tooltip.dataPoints ? tooltip.dataPoints : []

    const hoveredElementX = toolTipDataPoints[0]?.element?.x ?? 0
    const hoveredElementWidth = (toolTipDataPoints[0]?.element as any)?.width ?? 0

    useKeyboardHotkeys({
        escape: {
            action: () => {
                setIsDragging(false)
            },
        },
    })

    useEventListener(
        'mouseup',
        () => {
            if (!isDragging) {
                return
            }

            setIsDragging(false)

            if (!onSelectionChange || !toolTipDataPoints.length || !dragStartRef.current) {
                return
            }

            const startIndex = dragStartRef.current.index
            const endIndex = toolTipDataPoints[0].dataIndex
            dragStartRef.current = null

            if (typeof startIndex !== 'number' || typeof endIndex !== 'number') {
                return
            }

            if (startIndex !== endIndex) {
                onSelectionChange({
                    startIndex: Math.min(startIndex, endIndex),
                    endIndex: Math.max(startIndex, endIndex),
                })
            }
        },
        window,
        [isDragging, onSelectionChange]
    )

    const onMouseDown = (): void => {
        if (!onSelectionChange) {
            return
        }
        setIsDragging(true)
        dragStartRef.current = { index: toolTipDataPoints[0].dataIndex, x: hoveredElementX }
    }

    let selectionLeft = hoveredElementX
    let selectionWidth = 1

    if (isDragging && dragStartRef.current) {
        if (hoveredElementX === dragStartRef.current.x) {
            // If the same we just show it in the middle of the bar
        } else if (hoveredElementX > dragStartRef.current.x) {
            // If we are hovering past where we started we set it to be before the bar and after the next
            selectionLeft = dragStartRef.current.x - hoveredElementWidth / 2
            selectionWidth = hoveredElementX + hoveredElementWidth / 2 - selectionLeft
        } else {
            // If we are hovering before where we started we set it to be after the bar and before the next
            selectionLeft = hoveredElementX - hoveredElementWidth / 2
            selectionWidth = dragStartRef.current.x + hoveredElementWidth / 2 - selectionLeft
        }
    }

    return !loading ? (
        <div className={finalClassName} onMouseDown={onSelectionChange ? onMouseDown : undefined}>
            <canvas ref={canvasRef} />
            <>
                {tooltipVisible && onSelectionChange && (
                    <div className="absolute inset-0 pointer-events-none">
                        <div
                            className="rounded opacity-50 border absolute"
                            style={{
                                left: selectionLeft ?? 0,
                                width: selectionWidth,
                                height: '100%',
                                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                            }}
                        />
                    </div>
                )}
                <Popover
                    visible={tooltipVisible}
                    overlay={
                        <InsightTooltip
                            embedded
                            hideInspectActorsSection
                            showHeader={!!labels}
                            altTitle={
                                toolTipDataPoints.length > 0
                                    ? renderLabel
                                        ? renderLabel(toolTipDataPoints[0].label)
                                        : toolTipDataPoints[0].label
                                    : ''
                            }
                            seriesData={toolTipDataPoints.map((dp, i) => ({
                                id: i,
                                dataIndex: 0,
                                datasetIndex: 0,
                                order: i,
                                label: dp.dataset.label,
                                color: dp.dataset.borderColor as string,
                                count: (dp.dataset.data?.[dp.dataIndex] as number) || 0,
                            }))}
                            renderSeries={(value) => value}
                            renderCount={(count) => (renderCount ? renderCount(count) : humanFriendlyNumber(count))}
                        />
                    }
                    placement="bottom-start"
                    padded={false}
                >
                    <div ref={tooltipRef} />
                </Popover>
            </>
        </div>
    ) : (
        <LemonSkeleton className={finalClassName} />
    )
}
