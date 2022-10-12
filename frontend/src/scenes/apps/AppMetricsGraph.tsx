import React, { useEffect, useRef } from 'react'
import { getSeriesColor } from 'lib/colors'
import { Chart, ChartItem } from 'chart.js'
import { DescriptionColumns } from './constants'
import { MetricsOverviewProps } from './MetricsTab'
import { LemonSkeleton } from '../../lib/components/LemonSkeleton'

import './AppMetricsGraph.scss'

export function AppMetricsGraph({ tab, metrics, metricsLoading }: MetricsOverviewProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    const descriptions = DescriptionColumns[tab]

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && metrics) {
            const successColor = getSeriesColor(0)
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: metrics.dates,
                    datasets: [
                        {
                            label: descriptions.successes,
                            data: metrics.successes,
                            fill: true,
                            borderColor: successColor,
                        },
                        ...(descriptions.successes_on_retry
                            ? [
                                  {
                                      label: descriptions.successes_on_retry,
                                      data: metrics.successes_on_retry,
                                      fill: true,
                                      borderColor: successColor,
                                  },
                              ]
                            : []),
                        {
                            label: descriptions.failures,
                            data: metrics.failures,
                            fill: true,
                            borderColor: successColor,
                        },
                    ],
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
    }, [metrics])

    if (metricsLoading || !metrics) {
        return <LemonSkeleton className="AppMetricsGraph" />
    }

    return (
        <div className="AppMetricsGraph">
            <canvas ref={canvasRef} />
        </div>
    )
}
