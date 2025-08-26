import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Popover, SpinnerOverlay } from '@posthog/lemon-ui'

import { Chart, ChartDataset, ChartItem, ChartOptions } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber, inStorybookTestRunner } from 'lib/utils'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export type AppMetricColor = 'success' | 'danger' | 'warning' | 'data-color-1'

export type AppMetricsTrendProps = {
    timeSeries: AppMetricsTimeSeriesResponse | null
    colorMap?: Record<string, AppMetricColor>
    color?: AppMetricColor
    loading?: boolean
    mode?: 'full' | 'compact'
    className?: string
}

export function AppMetricsTrend({
    timeSeries,
    loading,
    colorMap,
    color,
    mode = 'full',
    className,
}: AppMetricsTrendProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [tooltipState, setTooltipState] = useState({ x: 0, y: 0, visible: false })

    const chartOptions = useMemo((): ChartOptions => {
        if (mode === 'compact') {
            return {
                scales: {
                    x: {
                        ticks: {
                            maxRotation: 0,
                            display: false,
                        },
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                    },
                    y: {
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                        beginAtZero: true,
                        ticks: {
                            maxRotation: 0,
                            display: false,
                            callback: function (value, index, ticks) {
                                // Show only first and last labels in compact mode
                                const res =
                                    index === 0 || index === ticks.length - 1
                                        ? this.getLabelForValue(Number(value))
                                        : undefined

                                return res
                            },
                        },
                    },
                },
                plugins: {
                    // @ts-expect-error Types of library are out of date
                    crosshair: false,
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        enabled: false, // Using external tooltip
                        external({ tooltip, chart }) {
                            setPopoverContent(
                                <InsightTooltip
                                    embedded
                                    hideInspectActorsSection
                                    // showHeader={!!labels}
                                    altTitle={tooltip.dataPoints[0].label}
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

                            const position = chart.canvas.getBoundingClientRect()
                            setTooltipState({
                                x: position.left + tooltip.caretX,
                                y: position.top + tooltip.caretY,
                                visible: tooltip.opacity > 0,
                            })
                        },
                    },
                },
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    axis: 'x',
                    intersect: false,
                },
            }
        }

        return {
            scales: {
                x: {
                    ticks: {
                        maxRotation: 0,
                    },
                    grid: {
                        display: false,
                    },
                },
                y: {
                    beginAtZero: true,
                },
            },
            plugins: {
                // @ts-expect-error Types of library are out of date
                crosshair: false,
                legend: {
                    display: false,
                },
                tooltip: {
                    enabled: false, // Using external tooltip
                    external({ tooltip, chart }) {
                        setPopoverContent(
                            <InsightTooltip
                                embedded
                                hideInspectActorsSection
                                // showHeader={!!labels}
                                altTitle={tooltip.dataPoints[0].label}
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

                        const position = chart.canvas.getBoundingClientRect()
                        setTooltipState({
                            x: position.left + tooltip.caretX,
                            y: position.top + tooltip.caretY,
                            visible: tooltip.opacity > 0,
                        })
                    },
                },
            },
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                axis: 'x',
                intersect: false,
            },
        }
    }, [mode])

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && !inStorybookTestRunner() && timeSeries) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: timeSeries.labels,
                    datasets: timeSeries.series.map((series) => {
                        const colorConfig = color
                            ? colorConfigFromVar(color)
                            : colorMap?.[series.name]
                              ? colorConfigFromVar(colorMap[series.name])
                              : colorConfigFromMetricName(series.name)

                        return {
                            label: series.name,
                            data: series.values,
                            ...colorConfig,
                        }
                    }),
                },
                options: chartOptions,
            })

            return () => {
                chart?.destroy()
            }
        }
    }, [timeSeries, colorMap, color, chartOptions])

    return (
        <div className={clsx('flex-1', className)}>
            {loading && <SpinnerOverlay />}
            {!!timeSeries && <canvas ref={canvasRef} />}
            <Popover
                visible={tooltipState.visible}
                overlay={popoverContent}
                placement="top"
                padded={false}
                className="pointer-events-none"
            >
                <div
                    className="fixed"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: tooltipState.x, top: tooltipState.y }}
                />
            </Popover>
        </div>
    )
}

function colorConfigFromVar(varName: string): Partial<ChartDataset<'line', any>> {
    const color = getColorVar(varName)

    return {
        borderColor: color,
        hoverBorderColor: color,
        hoverBackgroundColor: color,
        backgroundColor: color,
        fill: false,
        borderWidth: 2,
        pointRadius: 0,
    }
}

function colorConfigFromMetricName(name: string): Partial<ChartDataset<'line', any>> {
    switch (name) {
        case 'succeeded':
            return colorConfigFromVar('success')
        case 'failed':
            return colorConfigFromVar('danger')
        case 'dropped':
            return colorConfigFromVar('warning')
        default:
            return colorConfigFromVar('data-color-1')
    }
}
