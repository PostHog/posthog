import React, { useEffect, useMemo, useRef } from 'react'
import { dayjs } from 'lib/dayjs'
import { getSeriesColor } from 'lib/colors'
import { Card } from 'antd'
import { Chart, ChartItem } from 'chart.js'
import { range } from 'lib/utils'

export function MetricsTab(): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    const dates = useMemo(
        () =>
            range(0, 30)
                .map((i) => dayjs().subtract(i, 'days').format('D MMM YYYY'))
                .reverse(),
        []
    )

    const dataSuccess = useMemo(() => range(0, 30).map((x) => ((x + 2) % 7) * 100), [])

    const dataFail = useMemo(() => range(0, 30).map((x) => ((x + 2) % 7) * 1), [])

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current) {
            const successColor = getSeriesColor(0)
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: dates,
                    datasets: [
                        {
                            label: 'Events delivered on first try',
                            data: dataSuccess,
                            fill: true,
                            borderColor: successColor,
                        },
                        {
                            label: 'Events failed',
                            data: dataFail,
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
    }, [])

    return (
        <div className="mt-4">
            <Card title="Metrics overview">
                <div>
                    <div className="card-secondary">Events delivered on first try</div>
                    <div>568,048</div>
                </div>
                <div>
                    <div className="card-secondary">Events delivered on retry</div>
                    <div>134</div>
                </div>
                <div>
                    <div className="card-secondary">Events failed</div>
                    <div>0</div>
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
