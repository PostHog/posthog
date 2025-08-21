import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { Popover, SpinnerOverlay } from '@posthog/lemon-ui'

import { Chart, ChartDataset, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber, inStorybookTestRunner } from 'lib/utils'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'

import { AppMetricsLogicProps, appMetricsLogic } from './appMetricsLogic'

export type AppMetricsTrendProps = AppMetricsLogicProps & {
    colorMap?: Record<string, 'success' | 'danger' | 'warning' | 'data-color-1'>
}

export function AppMetricsTrend({ colorMap, ...props }: AppMetricsTrendProps): JSX.Element {
    const logic = appMetricsLogic(props)
    const { appMetricsTrends, appMetricsTrendsLoading } = useValues(logic)
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [tooltipState, setTooltipState] = useState({ x: 0, y: 0, visible: false })

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && appMetricsTrends && !inStorybookTestRunner()) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: appMetricsTrends.labels,
                    datasets: appMetricsTrends.series.map((series) => {
                        const colorConfig = colorMap?.[series.name]
                            ? colorConfigFromVar(colorMap[series.name])
                            : colorConfigFromMetricName(series.name)

                        return {
                            label: series.name,
                            data: series.values,
                            borderColor: '',
                            ...colorConfig,
                        }
                    }),
                },
                options: {
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
                },
            })

            return () => {
                chart?.destroy()
            }
        }
    }, [appMetricsTrends, colorMap])

    return (
        <div className="relative border rounded p-6 bg-surface-primary h-[50vh]">
            {appMetricsTrendsLoading && <SpinnerOverlay />}
            {!!appMetricsTrends && <canvas ref={canvasRef} />}
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
