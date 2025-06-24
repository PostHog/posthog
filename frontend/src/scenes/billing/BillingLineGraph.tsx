import 'chartjs-adapter-dayjs-3'

import { useValues } from 'kea'
import { Chart, ChartDataset, ChartOptions, TooltipModel } from 'lib/Chart'
import { getSeriesColor } from 'lib/colors'
import { getGraphColors } from 'lib/colors'
import { useCallback, useEffect, useRef } from 'react'
import { createRoot, Root } from 'react-dom/client'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { BillingLineGraphTooltip } from './BillingLineGraphTooltip'

export interface BillingSeriesType {
    id: number
    label: string
    data: number[]
    dates: string[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
}

export interface BillingLineGraphProps {
    series: BillingSeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
    interval?: 'day' | 'week' | 'month'
}

const defaultFormatter = (value: number): string => value.toLocaleString()

function useBillingTooltip(): {
    ensureBillingTooltip: () => [Root, HTMLElement]
    hideBillingTooltip: () => void
} {
    const tooltipElRef = useRef<HTMLElement | null>(null)
    const tooltipRootRef = useRef<Root | null>(null)

    const ensureBillingTooltip = useCallback((): [Root, HTMLElement] => {
        if (!tooltipElRef.current) {
            tooltipElRef.current = document.createElement('div')
            tooltipElRef.current.id = 'BillingTooltipWrapper'
            tooltipElRef.current.className =
                'BillingTooltipWrapper hidden absolute z-10 p-2 bg-bg-light rounded shadow-md text-xs pointer-events-none border border-border'
            document.body.appendChild(tooltipElRef.current)
        }
        if (!tooltipRootRef.current) {
            tooltipRootRef.current = createRoot(tooltipElRef.current)
        }
        return [tooltipRootRef.current, tooltipElRef.current]
    }, [])

    const hideBillingTooltip = useCallback((): void => {
        if (tooltipElRef.current) {
            tooltipElRef.current.classList.add('hidden')
            tooltipElRef.current.classList.remove('block')
        }
    }, [])

    useEffect(
        () => () => {
            if (tooltipRootRef.current) {
                setTimeout(() => tooltipRootRef.current?.unmount(), 0)
            }
            tooltipElRef.current?.remove()
        },
        []
    )

    return { ensureBillingTooltip, hideBillingTooltip }
}

export function SeriesColorDot({ colorIndex }: { colorIndex: number }): JSX.Element {
    return <div className={`series-color-dot series-color-dot-${colorIndex % 15}`} />
}

export function BillingLineGraph({
    series,
    dates,
    isLoading,
    hiddenSeries,
    valueFormatter = defaultFormatter,
    showLegend = true,
    interval = 'day',
}: BillingLineGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)
    const { ensureBillingTooltip, hideBillingTooltip } = useBillingTooltip()
    const { isDarkModeOn } = useValues(themeLogic)
    const graphColors = getGraphColors()

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
                        unit: interval,
                    },
                    ticks: {
                        source: 'labels',
                        color: graphColors.axisLabel || '#666666',
                    },
                    grid: {
                        display: false,
                    },
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: graphColors.axisLine || 'rgba(0, 0, 0, 0.1)',
                    },
                    ticks: {
                        callback: function (value) {
                            // Use the provided formatter, fallback shouldn't be needed due to default prop
                            return typeof value === 'number' ? valueFormatter(value) : value
                        },
                        color: graphColors.axisLabel || '#666666',
                    },
                },
            },
            plugins: {
                tooltip: {
                    enabled: false, // Disable default tooltip
                    external: ({ tooltip }: { chart: Chart; tooltip: TooltipModel<'line'> }) => {
                        if (!canvasRef.current) {
                            return
                        }

                        const [tooltipRoot, tooltipEl] = ensureBillingTooltip()

                        if (tooltip.opacity === 0 || !tooltip.body?.length) {
                            hideBillingTooltip()
                            return
                        }

                        // Process data points
                        try {
                            const title = tooltip.title?.[0] || ''
                            const dataPoints = tooltip.dataPoints || []

                            const sortedSeries = dataPoints
                                .map((point) => {
                                    // Add checks for dataset existence
                                    const dataset =
                                        point.datasetIndex < series.length ? series[point.datasetIndex] : null
                                    if (!dataset) {
                                        return null
                                    } // Skip if dataset index is out of bounds
                                    const value = point.parsed.y
                                    return {
                                        id: dataset.id,
                                        label: dataset.label,
                                        value: value,
                                        formattedValue: valueFormatter(value),
                                        color: getSeriesColor(dataset.id % 15),
                                        datasetIndex: point.datasetIndex,
                                    }
                                })
                                .filter((item): item is NonNullable<typeof item> => item !== null) // Filter out nulls
                                .sort((a, b) => b.value - a.value) // Sort descending by value

                            // Render custom tooltip content using the dedicated component
                            tooltipRoot.render(<BillingLineGraphTooltip title={title} sortedSeries={sortedSeries} />)

                            // Position tooltip after rendering to get dimensions
                            tooltipEl.classList.remove('hidden')
                            tooltipEl.classList.add('block')

                            const bounds = canvasRef.current.getBoundingClientRect()
                            const tooltipWidth = tooltipEl.offsetWidth
                            const tooltipHeight = tooltipEl.offsetHeight

                            const scrollX = window.scrollX
                            const scrollY = window.scrollY

                            let tooltipX = bounds.left + scrollX + tooltip.caretX + 8
                            let tooltipY = bounds.top + scrollY + tooltip.caretY - tooltipHeight / 2 // Center vertically

                            // Prevent tooltip going off-screen right
                            if (tooltipX + tooltipWidth > bounds.right + scrollX) {
                                tooltipX = bounds.left + scrollX + tooltip.caretX - tooltipWidth - 8
                            }
                            // Prevent tooltip going off-screen left
                            tooltipX = Math.max(tooltipX, bounds.left + scrollX)
                            // Prevent tooltip going off-screen top
                            tooltipY = Math.max(tooltipY, bounds.top + scrollY)
                            // Prevent tooltip going off-screen bottom
                            tooltipY = Math.min(tooltipY, bounds.bottom + scrollY - tooltipHeight)

                            tooltipEl.style.top = `${tooltipY}px`
                            tooltipEl.style.left = `${tooltipX}px`
                        } catch {
                            hideBillingTooltip()
                        }
                    },
                    mode: 'index',
                    intersect: false,
                },
                legend: {
                    display: showLegend,
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
    }, [
        series,
        dates,
        hiddenSeries,
        valueFormatter,
        showLegend,
        interval,
        ensureBillingTooltip,
        hideBillingTooltip,
        isDarkModeOn,
        graphColors,
    ])

    return (
        <div className="relative h-96">
            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-bg-light bg-opacity-75 z-10">
                    <div className="text-muted">Loading...</div>
                </div>
            )}
            <canvas ref={canvasRef} />
        </div>
    )
}
