import clsx from 'clsx'
import { ScaleOptions } from 'lib/Chart'
import { Chart, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect, useMemo, useRef, useState } from 'react'
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
    /** Optional labels for the X axis. */
    labels?: string[]
    /** Either a list of numbers for a muted graph or an array of time series */
    data: number[] | SparklineTimeSeries[]
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
    className?: string
}

export function Sparkline({
    labels,
    data,
    type = 'bar',
    maximumIndicator = true,
    loading = false,
    withXScale,
    withYScale,
    renderLabel,
    className,
}: SparklineProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const tooltipRef = useRef<HTMLDivElement | null>(null)

    const [isTooltipShown, setIsTooltipShown] = useState(false)
    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const adjustedData: SparklineTimeSeries[] = useMemo(() => {
        return !isSparkLineTimeSeries(data) ? [{ name: 'Count', color: 'muted', values: data }] : data
    }, [data])

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
                                setIsTooltipShown(tooltip.opacity > 0)
                                setPopoverContent(
                                    <InsightTooltip
                                        embedded
                                        hideInspectActorsSection
                                        showHeader={!!labels}
                                        altTitle={
                                            renderLabel
                                                ? renderLabel(tooltip.dataPoints[0].label)
                                                : tooltip.dataPoints[0].label
                                        }
                                        seriesData={tooltip.dataPoints.map((dp, i) => ({
                                            id: i,
                                            dataIndex: 0,
                                            datasetIndex: 0,
                                            order: i,
                                            label: dp.dataset.label,
                                            color: dp.dataset.borderColor as string,
                                            count: (dp.dataset.data?.[dp.dataIndex] as number) || 0,
                                        }))}
                                        renderSeries={(value) => value}
                                        renderCount={(count) => humanFriendlyNumber(count)}
                                    />
                                )
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

    return !loading ? (
        <div className={finalClassName}>
            <canvas ref={canvasRef} />
            <Popover visible={isTooltipShown} overlay={popoverContent} placement="bottom-start" padded={false}>
                <div ref={tooltipRef} />
            </Popover>
        </div>
    ) : (
        <LemonSkeleton className={finalClassName} />
    )
}

function isSparkLineTimeSeries(data: number[] | SparklineTimeSeries[]): data is SparklineTimeSeries[] {
    return typeof data[0] !== 'number'
}
