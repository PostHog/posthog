import React, { useEffect, useRef } from 'react'
import { getColorVar } from 'lib/colors'
import { Chart, ChartDataset, ChartItem } from 'chart.js'
import { DescriptionColumns } from './constants'
import { MetricsOverviewProps } from './MetricsTab'
import { LemonSkeleton } from '../../lib/components/LemonSkeleton'

import './AppMetricsGraph.scss'
import { lightenDarkenColor } from '../../lib/utils'

export function AppMetricsGraph({ tab, metrics, metricsLoading }: MetricsOverviewProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    const descriptions = DescriptionColumns[tab]

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && metrics) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: metrics.dates,
                    datasets: [
                        {
                            label: descriptions.successes,
                            data: metrics.successes,
                            borderColor: '',
                            ...colorConfig('data-brand-blue'),
                        },
                        ...(descriptions.successes_on_retry
                            ? [
                                  {
                                      label: descriptions.successes_on_retry,
                                      data: metrics.successes_on_retry,
                                      ...colorConfig('data-yellow'),
                                  },
                              ]
                            : []),
                        {
                            label: descriptions.failures,
                            data: metrics.failures,
                            ...colorConfig('data-pink'),
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

function colorConfig(baseColorVar: string): Partial<ChartDataset<'line', any>> {
    const mainColor = getColorVar(baseColorVar)

    return {
        borderColor: mainColor,
        hoverBorderColor: lightenDarkenColor(mainColor, -20),
        hoverBackgroundColor: lightenDarkenColor(mainColor, -20),
        backgroundColor: mainColor,
        fill: false,
        borderWidth: 2,
        pointRadius: 0,
    }
}
