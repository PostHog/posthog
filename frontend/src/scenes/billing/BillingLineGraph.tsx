import { Chart, ChartDataset, ChartOptions, TooltipItem } from 'chart.js'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { useEffect, useRef } from 'react'

// Interfaces (potentially move to a shared types file later)
export interface BillingSeriesType {
    id: number
    label: string
    data: number[]
    days: string[] // Dates associated with the data points
    count: number // Total count/sum for the series (used in table, might be removed from graph context later)
    compare?: boolean
    compare_label?: string
    breakdown_value?: string | string[]
}

export interface BillingLineGraphProps {
    series: BillingSeriesType[]
    dates: string[] // All dates for the x-axis labels
    isLoading?: boolean
    hiddenSeries: number[]
    /** Function to format the display of graph values (Y-axis and tooltips) */
    valueFormatter?: (value: number) => string
}

// Default formatter using locale string
const defaultFormatter = (value: number): string => value.toLocaleString()

// Component for color dot
export function SeriesColorDot({ colorIndex }: { colorIndex: number }): JSX.Element {
    return <div className={`series-color-dot series-color-dot-${colorIndex % 15}`} />
}

// Reusable BillingLineGraph component
export function BillingLineGraph({
    series,
    dates,
    isLoading,
    hiddenSeries,
    valueFormatter = defaultFormatter,
}: BillingLineGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    useEffect(() => {
        if (!canvasRef.current) {
            return
        }

        if (chartRef.current) {
            chartRef.current.destroy()
        }

        const visibleSeries = series.filter((s) => !hiddenSeries.includes(s.id))

        const datasets: ChartDataset<'line'>[] = visibleSeries.map((s) => ({
            label: s.label,
            data: s.data,
            borderColor: getSeriesColor(s.id % 15),
            backgroundColor: getSeriesColor(s.id % 15),
            borderWidth: 2,
            tension: 0.1,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: getSeriesColor(s.id % 15),
            pointHoverBorderColor: getSeriesColor(s.id % 15),
        }))

        const options: ChartOptions<'line'> = {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false,
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day',
                    },
                    grid: {
                        display: false,
                    },
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.1)',
                    },
                    ticks: {
                        callback: function (value) {
                            // Use the provided formatter, fallback shouldn't be needed due to default prop
                            return typeof value === 'number' ? valueFormatter(value) : value
                        },
                    },
                },
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        title: (context) => {
                            // Ensure context and parsed value exist
                            return context[0]?.parsed?.x ? dayjs(context[0].parsed.x).format('MMMM D, YYYY') : ''
                        },
                        label: (context: TooltipItem<'line'>) => {
                            let label = context.dataset.label || ''
                            if (label) {
                                label += ': '
                            }
                            if (context.parsed.y !== null) {
                                // Use the provided formatter
                                label += valueFormatter(context.parsed.y)
                            }
                            return label
                        },
                    },
                },
                legend: {
                    position: 'bottom',
                    labels: {
                        usePointStyle: true,
                        boxWidth: 6,
                    },
                },
            },
        }

        const ctx = canvasRef.current.getContext('2d')
        if (ctx) {
            chartRef.current = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dates,
                    datasets,
                },
                options,
            })
        }

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
            }
        }
    }, [series, dates, hiddenSeries, valueFormatter])

    return (
        <div className="relative h-96">
            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-white bg-opacity-75 z-10">
                    <div className="text-muted">Loading...</div>
                </div>
            )}
            <canvas ref={canvasRef} />
        </div>
    )
}
