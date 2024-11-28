import { useEffect, useRef } from 'react'
import { useValues } from 'kea'
import { Chart } from 'chart.js'
import { experimentLogic } from '../experimentLogic'
import { InsightType } from '~/types'

// Dimensions
const BORDER_WIDTH = 4
const BAR_HEIGHT = 15
const CORNER_RADIUS = 4

// Colors
const COLORS = {
    BOUNDARY_LINES: '#d0d0d0', // Darker gray for boundaries (changed from #e8e8e8)
    ZERO_LINE: '#666666', // Keeping zero line the darkest
    BAR_NEGATIVE: '#F44435', // Red for negative delta
    BAR_BEST: '#4DAF4F', // Green for best performer
    BAR_DEFAULT: '#d9d9d9', // Gray for other bars
    BAR_MIDDLE_POINT: 'black', // Black for the middle point marker
}

const intervalPlugin = {
    id: 'intervalPlugin',
    afterDatasetsDraw(chart: Chart) {
        const ctx = chart.ctx
        const data = chart.data.datasets[0].data

        // Find the highest conversion rate
        const maxConversion = Math.max(...data.map((d) => (d as any).x))

        chart.data.datasets.forEach((dataset, i) => {
            const meta = chart.getDatasetMeta(i)
            meta.data.forEach((point, index) => {
                const model = point.getProps(['x', 'y'])
                const lower = (dataset.data[index] as any).lower
                const upper = (dataset.data[index] as any).upper
                const currentX = (dataset.data[index] as any).x
                if (lower === undefined || upper === undefined) {
                    return
                }
                const xStart = chart.scales['x'].getPixelForValue(lower)
                const xEnd = chart.scales['x'].getPixelForValue(upper)
                const width = xEnd - xStart
                const yCenter = model.y

                // Determine color based on performance and delta
                let fillColor
                if (currentX < 0) {
                    fillColor = COLORS.BAR_NEGATIVE
                } else if (currentX === maxConversion) {
                    fillColor = COLORS.BAR_BEST
                } else {
                    fillColor = COLORS.BAR_DEFAULT
                }

                ctx.save()
                ctx.fillStyle = fillColor
                ctx.beginPath()
                ctx.roundRect(xStart, yCenter - BAR_HEIGHT / 2, width, BAR_HEIGHT, CORNER_RADIUS)
                ctx.fill()

                // Draw the middle point as a thin rectangle
                ctx.fillStyle = COLORS.BAR_MIDDLE_POINT
                const xMiddle = chart.scales['x'].getPixelForValue(currentX)
                ctx.fillRect(xMiddle - BORDER_WIDTH / 2, yCenter - BAR_HEIGHT / 2, BORDER_WIDTH, BAR_HEIGHT)

                ctx.restore()
            })
        })
    },
}

const zeroLinePlugin = {
    id: 'zeroLinePlugin',
    beforeDatasetsDraw(chart: Chart) {
        const ctx = chart.ctx
        const xScale = chart.scales['x']

        // Draw all tick lines first (dimmer)
        xScale.ticks.forEach((tick) => {
            const xPos = xScale.getPixelForValue(tick.value)
            ctx.save()
            ctx.beginPath()
            ctx.strokeStyle = COLORS.BOUNDARY_LINES
            ctx.moveTo(xPos, 0)
            ctx.lineTo(xPos, chart.height)
            ctx.stroke()
            ctx.restore()
        })

        // Draw zero line on top (more prominent)
        const zeroX = xScale.getPixelForValue(0)
        ctx.save()
        ctx.beginPath()
        ctx.strokeStyle = COLORS.ZERO_LINE
        ctx.moveTo(zeroX, 0)
        ctx.lineTo(zeroX, chart.height)
        ctx.stroke()
        ctx.restore()
    },
}

export function DeltaViz(): JSX.Element {
    const { experimentResults, tabularExperimentResults, getMetricType, metricResults } = useValues(experimentLogic)

    if (!experimentResults) {
        return <></>
    }

    const variants = tabularExperimentResults.filter((variant) => variant.key !== 'control')
    const chartHeight =
        variants.length === 1
            ? 120 // Single variant gets 120px
            : variants.length * 60 // Multiple variants get 60px each

    // Create an array of all results to render, starting with the main experiment results
    // const allResults = [experimentResults, ...(metricResults || [])]
    const allResults = [...(metricResults || [])]

    return (
        <div>
            {allResults.map((results, metricIndex) => {
                if (!results) {
                    return null
                }

                const isFirstMetric = metricIndex === 0
                const adjustedChartHeight = chartHeight
                // const adjustedChartHeight = isFirstMetric ? chartHeight + 50 : chartHeight

                return (
                    <div key={metricIndex}>
                        {/* Chart */}
                        <div
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                height: `${adjustedChartHeight}px`,
                                border: '1px solid #e8e8e8',
                                borderRadius: isFirstMetric
                                    ? '4px 4px 0 0'
                                    : metricIndex === allResults.length - 1
                                    ? '0 0 4px 4px'
                                    : '0',
                                backgroundColor: '#f9faf7',
                            }}
                        >
                            <DeltaChart results={results} variants={variants} metricType={getMetricType(metricIndex)} />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

// New component to handle individual chart rendering
function DeltaChart({
    results,
    variants,
    metricType,
}: {
    results: any
    variants: any[]
    metricType: InsightType
}): JSX.Element {
    const chartRef = useRef<HTMLCanvasElement | null>(null)
    const chartInstance = useRef<Chart | null>(null)

    const { tabularExperimentResults, credibleIntervalForVariant, conversionRateForVariant, metricResults } =
        useValues(experimentLogic)

    // Determine if this is the first metric chart
    const isFirstMetric = !metricResults || metricResults.indexOf(results) === 0

    useEffect(() => {
        if (!chartRef.current || !results) {
            return
        }

        if (chartInstance.current) {
            chartInstance.current.destroy()
        }

        const ctx = chartRef.current.getContext('2d')
        if (!ctx) {
            return
        }

        const controlConversionRate = conversionRateForVariant(results, 'control')

        const chartData = tabularExperimentResults
            .filter((variant) => variant.key !== 'control')
            .map((variant) => {
                const credibleInterval = credibleIntervalForVariant(results, variant.key, metricType)
                const lower = credibleInterval[0] / 100
                const upper = credibleInterval[1] / 100
                const variantConversionRate = conversionRateForVariant(results, variant.key)

                // Calculate relative delta instead of using raw conversion rate
                let relativeDelta = 0
                if (controlConversionRate && variantConversionRate) {
                    relativeDelta = (variantConversionRate - controlConversionRate) / controlConversionRate
                }

                return {
                    x: relativeDelta, // This is now the relative delta instead of raw conversion rate
                    y: variant.key,
                    lower,
                    upper,
                }
            })

        // Find the maximum absolute value from either direction
        const maxAbsValue = Math.max(
            Math.abs(Math.min(...chartData.map((d) => d.lower))),
            Math.abs(Math.max(...chartData.map((d) => d.upper)))
        )

        // Add 5% padding to the range
        const padding = Math.max(maxAbsValue * 0.05, 0.02) // At least 2% padding
        const boundaryValue = maxAbsValue + padding

        // Set symmetric bounds
        const chartMin = -boundaryValue
        const chartMax = boundaryValue

        chartInstance.current = new Chart(ctx, {
            type: 'scatter',
            data: {
                labels: tabularExperimentResults.filter((v) => v.key !== 'control').map((v) => v.key),
                datasets: [
                    {
                        data: chartData,
                        backgroundColor: '#5f9d32',
                        borderColor: '#5f9d32',
                        borderWidth: 1,
                        pointRadius: 0,
                        hoverBorderColor: 'transparent',
                        hoverBackgroundColor: 'transparent',
                    },
                    {
                        data: chartData.flatMap((d) => [
                            { x: d.lower, y: d.y, bound: 'lower', value: d.lower },
                            { x: d.upper, y: d.y, bound: 'upper', value: d.upper },
                        ]),
                        backgroundColor: 'transparent',
                        borderColor: 'transparent',
                        pointStyle: 'rect',
                        pointRadius: 10,
                        hoverBackgroundColor: 'transparent',
                        hoverBorderColor: 'transparent',
                        hoverRadius: 10,
                    },
                    {
                        data: chartData.map((d) => ({ x: d.x, y: d.y })),
                        backgroundColor: 'transparent',
                        borderColor: 'transparent',
                        pointStyle: 'rect',
                        pointRadius: 10,
                        hoverBackgroundColor: 'transparent',
                        hoverBorderColor: 'transparent',
                        hoverRadius: 10,
                    },
                ],
            },
            options: {
                indexAxis: 'y',
                layout: {
                    padding: {
                        left: 50,
                        right: 50,
                    },
                },
                scales: {
                    x: {
                        position: 'top',
                        beginAtZero: false,
                        min: chartMin,
                        max: chartMax,
                        ticks: {
                            display: isFirstMetric,
                            callback: function (value) {
                                return `${(Number(value) * 100).toFixed(0)}%`
                            },
                            backdropColor: '#f9faf7',
                            backdropPadding: {
                                top: 8,
                                bottom: 8,
                                left: 12,
                                right: 12,
                            },
                            z: 2,
                        },
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                    },
                    y: {
                        type: 'category',
                        offset: true,
                        ticks: {
                            display: false,
                            // padding: 0,
                        },
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                        min: 0,
                        max: chartData.length,
                    },
                },
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const item = context.raw as any
                                if (item.bound) {
                                    return `${item.y} ${item.bound} bound: ${(item.value * 100).toFixed(2)}%`
                                }
                                if (item.x !== undefined && item.y !== undefined) {
                                    return `${item.y} conversion rate: ${(item.x * 100).toFixed(2)}%`
                                }
                                return ''
                            },
                        },
                    },
                    crosshair: {
                        enabled: false,
                        sync: {
                            enabled: false,
                        },
                        zoom: {
                            enabled: false,
                        },
                        line: {
                            enabled: false,
                            color: 'transparent', // Make the line transparent
                        },
                    },
                },
                maintainAspectRatio: false,
                responsive: true,
                hover: {
                    mode: 'nearest',
                    intersect: true,
                },
                events: ['mousemove', 'mouseout', 'click', 'touchstart', 'touchmove'],
                interaction: {
                    intersect: true,
                    mode: 'nearest',
                },
                pan: {
                    enabled: false,
                },
                zoom: {
                    enabled: false,
                    drag: {
                        enabled: false,
                    },
                    mode: 'none',
                },
            },
            plugins: [intervalPlugin, zeroLinePlugin],
        })

        return () => {
            if (chartInstance.current) {
                chartInstance.current.destroy()
            }
        }
    }, [results, variants, isFirstMetric])

    return <canvas ref={chartRef} />
}
