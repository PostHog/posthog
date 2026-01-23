import { useChart } from 'lib/hooks/useChart'

import { ProcessedChartData } from '../../experimentTimeseriesLogic'
import { useChartColors } from '../shared/colors'

interface VariantTimeseriesChartProps {
    chartData: ProcessedChartData
    isRatioMetric?: boolean
}

export function VariantTimeseriesChart({
    chartData: data,
    isRatioMetric = false,
}: VariantTimeseriesChartProps): JSX.Element {
    const colors = useChartColors()

    const { canvasRef } = useChart({
        getConfig: () => {
            if (!data) {
                return null
            }

            const { labels, datasets, processedData } = data

            return {
                type: 'line' as const,
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
                                color: colors.EXPOSURES_AXIS_LINES,
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
                                label: function (context) {
                                    const value = context.parsed.y
                                    if (value === null) {
                                        return ''
                                    }
                                    const formattedValue = `${(value * 100).toFixed(2)}%`
                                    return `${context.dataset.label}: ${formattedValue}`
                                },
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

                                        if (dataPoint && !dataPoint.hasRealData) {
                                            lines.push('⚠️ Data pending - showing last known value')
                                        }

                                        if (dataPoint) {
                                            if (isRatioMetric) {
                                                if (dataPoint.denominator_sum) {
                                                    lines.push(
                                                        `Denominator: ${dataPoint.denominator_sum.toLocaleString()}`
                                                    )
                                                }
                                            } else {
                                                if (dataPoint.number_of_samples) {
                                                    lines.push(
                                                        `Exposures: ${dataPoint.number_of_samples.toLocaleString()}`
                                                    )
                                                }
                                            }
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
                        crosshair: false,
                    },
                },
            }
        },
        deps: [data, colors.EXPOSURES_AXIS_LINES, isRatioMetric],
    })

    return (
        <div className="relative h-[224px]">
            <canvas ref={canvasRef} />
        </div>
    )
}
