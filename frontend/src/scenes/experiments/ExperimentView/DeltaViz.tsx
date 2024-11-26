import { useEffect, useRef } from 'react'
import { useValues } from 'kea'
import { Chart, CategoryScale, LinearScale, PointElement, ScatterController } from 'chart.js'
import { experimentLogic } from '../experimentLogic'

// Register required Chart.js components
Chart.register(CategoryScale, LinearScale, PointElement, ScatterController)

const BORDER_WIDTH = 2
const BORDER_HEIGHT = 20

const intervalPlugin = {
    id: 'intervalPlugin',
    afterDatasetsDraw(chart: Chart) {
        const ctx = chart.ctx
        chart.data.datasets.forEach((dataset, i) => {
            const meta = chart.getDatasetMeta(i)
            meta.data.forEach((point, index) => {
                const model = point.getProps(['x', 'y'])
                const lower = (dataset.data[index] as any).lower
                const upper = (dataset.data[index] as any).upper
                if (lower === undefined || upper === undefined) {
                    return
                }
                const xStart = chart.scales['x'].getPixelForValue(lower)
                const xEnd = chart.scales['x'].getPixelForValue(upper)
                const width = xEnd - xStart
                const yCenter = model.y

                // Draw the interval bar
                ctx.save()
                ctx.fillStyle = dataset.backgroundColor as string
                ctx.fillRect(xStart, yCenter - BORDER_HEIGHT / 2, width, BORDER_HEIGHT)

                // Draw the thin border rectangles
                ctx.fillStyle = 'black'
                ctx.fillRect(xStart, yCenter - BORDER_HEIGHT / 2, BORDER_WIDTH, BORDER_HEIGHT)
                ctx.fillRect(xEnd - BORDER_WIDTH, yCenter - BORDER_HEIGHT / 2, BORDER_WIDTH, BORDER_HEIGHT)

                ctx.restore()
            })
        })
    },
}

export function DeltaViz(): JSX.Element {
    const chartRef = useRef<HTMLCanvasElement | null>(null)
    const chartInstance = useRef<Chart | null>(null)
    const {
        experimentResults,
        tabularExperimentResults,
        getMetricType,
        credibleIntervalForVariant,
        conversionRateForVariant,
    } = useValues(experimentLogic)

    useEffect(() => {
        if (!chartRef.current || !experimentResults) {
            return
        }

        if (chartInstance.current) {
            chartInstance.current.destroy()
        }

        const ctx = chartRef.current.getContext('2d')
        if (!ctx) {
            return
        }

        const metricType = getMetricType(0)

        const chartData = tabularExperimentResults
            .filter((variant) => variant.key !== 'control')
            .map((variant) => {
                const credibleInterval = credibleIntervalForVariant(experimentResults, variant.key, metricType)
                const lower = credibleInterval[0] / 100
                const upper = credibleInterval[1] / 100
                const conversionRate = conversionRateForVariant(experimentResults, variant.key)

                return {
                    x: conversionRate ? conversionRate / 100 : (lower + upper) / 2,
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
                        label: 'Credible Intervals',
                        data: chartData,
                        backgroundColor: 'rgba(0, 123, 255, 0.5)',
                        borderColor: 'rgba(0, 123, 255, 1)',
                        borderWidth: 1,
                        pointStyle: 'rect',
                        pointRadius: 10,
                        hoverRadius: 10,
                    },
                    {
                        label: 'Interval Bounds',
                        data: chartData.flatMap((d) => [
                            { x: d.lower, y: d.y, bound: 'lower', value: d.lower },
                            { x: d.upper, y: d.y, bound: 'upper', value: d.upper },
                        ]),
                        pointStyle: 'rect',
                        pointRadius: 10,
                        backgroundColor: 'transparent',
                        borderColor: 'transparent',
                        hoverBackgroundColor: 'transparent',
                        hoverBorderColor: 'transparent',
                        hoverRadius: 10,
                    },
                ],
            },
            options: {
                indexAxis: 'y',
                scales: {
                    x: {
                        beginAtZero: false,
                        min: chartMin,
                        max: chartMax,
                        ticks: {
                            callback: (value: number) => `${(value * 100).toFixed(2)}%`,
                        },
                    },
                    y: {
                        type: 'category',
                        offset: true,
                        ticks: {
                            padding: 20,
                        },
                    },
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const item = context.raw as any
                                if (item.bound) {
                                    return `${item.y} ${item.bound} bound: ${(item.value * 100).toFixed(2)}%`
                                }
                                return ''
                            },
                        },
                    },
                },
                maintainAspectRatio: false,
            },
            plugins: [intervalPlugin],
        })

        return () => {
            if (chartInstance.current) {
                chartInstance.current.destroy()
            }
        }
    }, [experimentResults, tabularExperimentResults])

    if (!experimentResults) {
        return <></>
    }

    return (
        <div style={{ height: '400px' }}>
            <canvas ref={chartRef} />
        </div>
    )
}
