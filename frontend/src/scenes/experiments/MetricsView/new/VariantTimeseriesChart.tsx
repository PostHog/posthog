import { useEffect, useRef } from 'react'

import { Chart, ChartConfiguration } from 'lib/Chart'

import { ProcessedChartData } from '../../experimentTimeseriesLogic'

interface VariantTimeseriesChartProps {
    chartData: ProcessedChartData
}

export function VariantTimeseriesChart({ chartData: data }: VariantTimeseriesChartProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    useEffect(() => {
        if (!data) {
            return
        }

        // Use setTimeout to ensure the canvas is in the DOM
        const timeoutId = setTimeout(() => {
            const ctx = canvasRef.current
            if (!ctx) {
                console.error('Canvas element not found')
                return
            }

            // Destroy existing chart if it exists
            const existingChart = Chart.getChart(ctx)
            if (existingChart) {
                existingChart.destroy()
            }

            ctx.style.width = '100%'
            ctx.style.height = '100%'

            const { labels, datasets, processedData } = data

            const config: ChartConfiguration = {
                type: 'line',
                data: { labels, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'nearest',
                        axis: 'x',
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: {
                                display: true,
                                color: 'rgba(200, 200, 200, 0.3)',
                            },
                            ticks: {
                                count: 6,
                                callback: (value) => {
                                    const num = Number(value)
                                    if (Math.abs(num) < 1) {
                                        return `${(num * 100).toFixed(1)}%`
                                    }
                                    return num.toFixed(2)
                                },
                            },
                        },
                        x: {
                            grid: {
                                display: false,
                            },
                        },
                    },
                    plugins: {
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            callbacks: {
                                labelPointStyle: function () {
                                    return {
                                        pointStyle: 'circle',
                                        rotation: 0,
                                    }
                                },
                                afterBody: function (context) {
                                    if (context.length > 0) {
                                        const dataIndex = context[0].dataIndex
                                        const dataPoint = processedData[dataIndex]
                                        const lines = []

                                        // Show if data is pending/interpolated
                                        if (dataPoint && !dataPoint.hasRealData) {
                                            lines.push('⚠️ Data pending - showing last known value')
                                        }

                                        if (dataPoint && dataPoint.number_of_samples) {
                                            lines.push(`Samples: ${dataPoint.number_of_samples.toLocaleString()}`)
                                        }
                                        if (dataPoint && dataPoint.significant !== undefined) {
                                            lines.push(`Significant: ${dataPoint.significant ? 'Yes' : 'No'}`)
                                        }
                                        return lines
                                    }
                                    return []
                                },
                            },
                            usePointStyle: true,
                            boxWidth: 16,
                            boxHeight: 1,
                        },
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                    },
                },
            }

            chartRef.current = new Chart(ctx, config)
        }, 0)

        return () => {
            clearTimeout(timeoutId)
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
        }
    }, [data])

    return (
        <div className="relative h-[224px]">
            <canvas ref={canvasRef} />
        </div>
    )
}
