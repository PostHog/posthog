import { Chart, ChartDataset, ChartOptions, TooltipModel } from 'chart.js'
import { getSeriesColor } from 'lib/colors'
import React, { useEffect, useRef } from 'react'
import { createRoot, Root } from 'react-dom/client'

import { BillingLineGraphTooltip } from './BillingLineGraphTooltip'

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
    /** Function to format the display of graph values (Y-axis and tooltips) */
    valueFormatter?: (value: number) => string
    /** Whether to show the chart legend (default: true) */
    showLegend?: boolean
}

export interface BillingLineGraphProps {
    series: BillingSeriesType[]
    dates: string[] // All dates for the x-axis labels
    isLoading?: boolean
    hiddenSeries: number[]
    /** Function to format the display of graph values (Y-axis and tooltips) */
    valueFormatter?: (value: number) => string
    /** Whether to show the chart legend (default: true) */
    showLegend?: boolean
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
    showLegend = true, // Default legend to true
}: BillingLineGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    // Tooltip state
    const tooltipRootRef = useRef<Root | null>(null)
    const tooltipElRef = useRef<HTMLElement | null>(null)

    // Ensure tooltip elements exist
    function ensureBillingTooltip(): [Root, HTMLElement] {
        if (!tooltipElRef.current) {
            tooltipElRef.current = document.createElement('div')
            tooltipElRef.current.id = 'BillingTooltipWrapper'
            // Initial style: hidden but present
            tooltipElRef.current.className =
                'BillingTooltipWrapper hidden absolute z-10 p-2 bg-bg-light rounded shadow-md text-xs pointer-events-none border border-border'
            document.body.appendChild(tooltipElRef.current)
        }
        if (!tooltipRootRef.current) {
            tooltipRootRef.current = createRoot(tooltipElRef.current)
        }
        return [tooltipRootRef.current, tooltipElRef.current]
    }

    // Hide tooltip
    function hideBillingTooltip(): void {
        if (tooltipElRef.current) {
            tooltipElRef.current.classList.add('hidden')
            tooltipElRef.current.classList.remove('block') // Ensure block is removed
        }
    }

    // Cleanup tooltip on unmount
    useEffect(() => {
        return () => {
            if (tooltipRootRef.current) {
                // Wait for potential renders to finish before unmounting
                setTimeout(() => tooltipRootRef.current?.unmount(), 0)
            }
            tooltipElRef.current?.remove()
        }
    }, [])

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

                            // Position tooltip AFTER rendering to get dimensions
                            tooltipEl.classList.remove('hidden') // Make visible before positioning
                            tooltipEl.classList.add('block')

                            const bounds = canvasRef.current.getBoundingClientRect()
                            const tooltipWidth = tooltipEl.offsetWidth
                            const tooltipHeight = tooltipEl.offsetHeight

                            let tooltipX = bounds.left + window.pageXOffset + tooltip.caretX + 8
                            let tooltipY = bounds.top + window.pageYOffset + tooltip.caretY - tooltipHeight / 2 // Center vertically

                            // Prevent tooltip going off-screen right
                            if (tooltipX + tooltipWidth > bounds.right + window.pageXOffset) {
                                tooltipX = bounds.left + window.pageXOffset + tooltip.caretX - tooltipWidth - 8
                            }
                            // Prevent tooltip going off-screen left
                            tooltipX = Math.max(tooltipX, bounds.left + window.pageXOffset)
                            // Prevent tooltip going off-screen top
                            tooltipY = Math.max(tooltipY, bounds.top + window.pageYOffset)
                            // Prevent tooltip going off-screen bottom
                            tooltipY = Math.min(tooltipY, bounds.bottom + window.pageYOffset - tooltipHeight)

                            tooltipEl.style.top = `${tooltipY}px`
                            tooltipEl.style.left = `${tooltipX}px`
                        } catch (e) {
                            console.error('[Billing Tooltip] Error during rendering:', e)
                            hideBillingTooltip()
                        }
                    },
                    mode: 'index',
                    intersect: false,
                },
                legend: {
                    display: showLegend, // Control legend display via prop
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
            // No need to cleanup tooltip here, handled by component unmount effect
        }
    }, [series, dates, hiddenSeries, valueFormatter, showLegend])

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
