import React, { useEffect, useRef } from 'react'
import { getSeriesColor } from 'lib/colors'
import { Card } from 'antd'
import { Chart, ChartItem } from 'chart.js'
import { useValues } from 'kea'
import { appMetricsSceneLogic } from './appMetricsSceneLogic'

export function MetricsTab(): JSX.Element {
    const { metrics, metricsLoading } = useValues(appMetricsSceneLogic)

    const canvasRef = useRef<HTMLCanvasElement | null>(null)

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
                            label: 'Events delivered on first try',
                            data: metrics.successes,
                            fill: true,
                            borderColor: successColor,
                        },
                        {
                            label: 'Events delivered on retry',
                            data: metrics.successes_on_retry,
                            fill: true,
                            borderColor: successColor,
                        },
                        {
                            label: 'Events failed',
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
        return <></>
    }

    // :TODO: Format numbers
    return (
        <div className="mt-4">
            <Card title="Metrics overview">
                <div>
                    <div className="card-secondary">Events delivered on first try</div>
                    <div>{metrics.totals.successes}</div>
                </div>
                <div>
                    <div className="card-secondary">Events delivered on retry</div>
                    <div>{metrics.totals.successes_on_retry}</div>
                </div>
                <div>
                    <div className="card-secondary">Events failed</div>
                    <div>{metrics.totals.failures}</div>
                </div>
            </Card>

            <Card title="graph" className="mt-4">
                <div style={{ height: '300px' }}>
                    <canvas ref={canvasRef} />
                </div>
            </Card>
        </div>
    )
}
