import './AppMetricsGraph.scss'

import { Chart, ChartDataset, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { inStorybookTestRunner, lightenDarkenColor } from 'lib/utils'
import { useEffect, useRef } from 'react'

import { AppMetricsTab } from '~/types'

import { AppMetrics } from './appMetricsSceneLogic'
import { DescriptionColumns } from './constants'

export interface AppMetricsGraphProps {
    tab: AppMetricsTab
    metrics?: AppMetrics | null
    metricsLoading: boolean
}

export function AppMetricsGraph({ tab, metrics, metricsLoading }: AppMetricsGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    const descriptions = DescriptionColumns[tab]

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && metrics && !inStorybookTestRunner()) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: metrics.dates,
                    datasets: [
                        {
                            label: descriptions.successes,
                            data: metrics.successes,
                            borderColor: '',
                            ...colorConfig('data-color-1'),
                        },
                        {
                            label: descriptions.failures,
                            data: metrics.failures,
                            ...colorConfig('data-color-5'),
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

            return () => {
                chart?.destroy()
            }
        }
    }, [metrics])

    if (metricsLoading || !metrics) {
        return <LemonSkeleton className="AppMetricsGraph border rounded p-6" />
    }

    return (
        <div className="AppMetricsGraph border rounded p-6">
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
