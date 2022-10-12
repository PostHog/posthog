import React, { useEffect, useRef } from 'react'
import { getSeriesColor } from 'lib/colors'
import { Card } from 'antd'
import { Chart, ChartItem } from 'chart.js'
import { AppMetrics, AppMetricsTab } from './appMetricsSceneLogic'
import { DescriptionColumns } from './constants'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'

export interface MetricsTabProps {
    tab: AppMetricsTab
    metrics: AppMetrics | null
    metricsLoading: boolean
}

export function MetricsTab({ tab, metrics, metricsLoading }: MetricsTabProps): JSX.Element {
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

    return (
        <div className="mt-4">
            <MetricsOverview tab={tab} metrics={metrics} metricsLoading={metricsLoading} />

            <Card title="graph" className="mt-4">
                <div style={{ height: '300px' }}>
                    <canvas ref={canvasRef} />
                </div>
            </Card>
        </div>
    )
}

export function MetricsOverview({ tab, metrics, metricsLoading }: MetricsTabProps): JSX.Element {
    return (
        <Card title="Metrics overview">
            <div>
                <div className="card-secondary">{DescriptionColumns[tab].success}</div>
                <div>{renderNumber(metrics?.totals?.successes, metricsLoading)}</div>
            </div>
            {DescriptionColumns[tab].success_on_retry && (
                <div>
                    <div className="card-secondary">{DescriptionColumns[tab].success_on_retry}</div>
                    <div>{renderNumber(metrics?.totals?.successes_on_retry, metricsLoading)}</div>
                </div>
            )}
            <div>
                <div className="card-secondary">{DescriptionColumns[tab].failure}</div>
                <div>{renderNumber(metrics?.totals?.failures, metricsLoading)}</div>
            </div>
        </Card>
    )
}

function renderNumber(value: number | undefined, loading: boolean): JSX.Element {
    if (loading) {
        return <LemonSkeleton />
    }
    // :TODO: Format numbers
    return <>{value}</>
}
