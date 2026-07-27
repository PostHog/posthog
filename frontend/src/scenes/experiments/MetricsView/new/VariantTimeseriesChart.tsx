import { useChart } from 'lib/hooks/useChart'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'

import { ProcessedChartData } from '../../experimentTimeseriesLogic'
import { useChartColors } from '../shared/colors'
import { VariantTimeseriesTooltip } from './VariantTimeseriesTooltip'

interface VariantTimeseriesChartProps {
    chartData: ProcessedChartData
    isRatioMetric?: boolean
}

export function VariantTimeseriesChart({
    chartData: data,
    isRatioMetric = false,
}: VariantTimeseriesChartProps): JSX.Element {
    const colors = useChartColors()
    const { getTooltip, showTooltip, hideTooltip, positionTooltip } = useInsightTooltip()

    const { canvasRef } = useChart<'line'>({
        getConfig: () => {
            if (!data) {
                return null
            }

            const { labels, datasets, processedData, computedAt } = data

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
                            grid: {
                                display: true,
                                color: (context) => {
                                    if (context.tick.value === 0) {
                                        return colors.ZERO_LINE
                                    }
                                    return colors.EXPOSURES_AXIS_LINES
                                },
                                lineWidth: (context) => {
                                    if (context.tick.value === 0) {
                                        return 1.25
                                    }
                                    return 1
                                },
                            },
                            ticks: {
                                callback: (value) => {
                                    const num = Number(value)
                                    return `${(num * 100).toFixed(0)}%`
                                },
                            },
                            afterBuildTicks: (axis) => {
                                const ticks = axis.ticks.map((t) => t.value)
                                if (!ticks.includes(0)) {
                                    axis.ticks.push({ value: 0 })
                                    axis.ticks.sort((a, b) => a.value - b.value)
                                }
                                // When 0 is the lowest tick, pad below so it doesn't
                                // overlap with x-axis date labels
                                if (axis.ticks.length > 1 && axis.ticks[0].value === 0) {
                                    const tickStep = axis.ticks[1].value - axis.ticks[0].value
                                    axis.min = -tickStep * 0.3
                                }
                            },
                        },
                        x: {
                            grid: {
                                display: false,
                            },
                            ticks: {
                                maxRotation: 45,
                                minRotation: 45,
                            },
                        },
                    },
                    plugins: {
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            enabled: false,
                            external: ({ chart, tooltip }) => {
                                const canvas = chart.canvas
                                if (!canvas) {
                                    return
                                }

                                const [tooltipRoot, tooltipEl] = getTooltip()

                                if (tooltip.opacity === 0 || !tooltip.dataPoints?.length) {
                                    hideTooltip()
                                    return
                                }

                                const dataIndex = tooltip.dataPoints[0].dataIndex
                                const dataPoint = processedData[dataIndex]
                                if (!dataPoint) {
                                    hideTooltip()
                                    return
                                }

                                showTooltip()
                                tooltipRoot.render(
                                    <VariantTimeseriesTooltip
                                        date={dataPoint.date}
                                        delta={dataPoint.value}
                                        lowerBound={dataPoint.lower_bound}
                                        upperBound={dataPoint.upper_bound}
                                        isRatioMetric={isRatioMetric}
                                        exposures={dataPoint.number_of_samples}
                                        denominator={dataPoint.denominator_sum}
                                        significant={dataPoint.significant}
                                        hasRealData={dataPoint.hasRealData}
                                        computedAt={computedAt}
                                    />
                                )

                                const bounds = canvas.getBoundingClientRect()
                                positionTooltip(tooltipEl, bounds, tooltip.caretX, 0, false)
                            },
                        },
                        crosshair: false,
                    },
                },
            }
        },
        deps: [data, colors.EXPOSURES_AXIS_LINES, colors.ZERO_LINE, isRatioMetric],
    })

    return (
        <div className="relative h-[224px]">
            <canvas ref={canvasRef} />
        </div>
    )
}
