import './BillingLineGraph.scss'

import 'chartjs-adapter-dayjs-3'
import annotationPlugin from 'chartjs-plugin-annotation'
import { useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { IconInfo } from '@posthog/icons'

import { Chart, ChartDataset, ChartOptions, TooltipModel } from 'lib/Chart'
import { getSeriesColor } from 'lib/colors'
import { getGraphColors } from 'lib/colors'
import { Dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { BillingLineGraphTooltip } from './BillingLineGraphTooltip'
import { useBillingMarkersPositioning } from './useBillingMarkersPositioning'

Chart.register(annotationPlugin)

export interface BillingSeriesType {
    id: number
    label: string
    data: number[]
    dates: string[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
}

export interface BillingPeriodMarker {
    date: Dayjs
}

export interface BillingLineGraphProps {
    series: BillingSeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
    valueFormatter?: (value: number) => string
    showLegend?: boolean
    interval?: 'day' | 'week' | 'month'
    billingPeriodMarkers?: BillingPeriodMarker[]
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

    useOnMountEffect(() => {
        return () => {
            if (tooltipRootRef.current) {
                tooltipRootRef.current.unmount()
            }
            tooltipElRef.current?.remove()
        }
    })

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
    billingPeriodMarkers = [],
}: BillingLineGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)
    const [chartReady, setChartReady] = useState(false)
    const [chartDimensions, setChartDimensions] = useState({ width: 0, height: 0 })
    const [axisLabelColor, setAxisLabelColor] = useState('#666666')
    const [markersReady, setMarkersReady] = useState(false)
    const [stableChartAreaLeft, setStableChartAreaLeft] = useState<number | null>(null)
    const markerTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const { ensureBillingTooltip, hideBillingTooltip } = useBillingTooltip()
    const { isDarkModeOn } = useValues(themeLogic)

    const { chartAreaLeft, chartAreaTop, getMarkerPosition } = useBillingMarkersPositioning(
        chartRef.current || undefined,
        chartDimensions.width,
        chartDimensions.height
    )

    useEffect(() => {
        if (!canvasRef.current) {
            return
        }

        if (chartRef.current) {
            chartRef.current.destroy()
        }

        const visibleSeries = series.filter((s) => !hiddenSeries.includes(s.id))
        const graphColors = getGraphColors()
        const currentAxisLabelColor = graphColors.axisLabel || '#666666'
        setAxisLabelColor(currentAxisLabelColor)

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
                        displayFormats: {
                            day: 'MMM DD',
                        },
                    },
                    ticks: {
                        source: 'labels',
                        color: currentAxisLabelColor,
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
                        color: currentAxisLabelColor,
                    },
                },
            },
            plugins: {
                // @ts-expect-error Types of library are out of date
                crosshair: false,
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
                                        point.datasetIndex < visibleSeries.length
                                            ? visibleSeries[point.datasetIndex]
                                            : null
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
                annotation: {
                    annotations: billingPeriodMarkers.reduce((acc: Record<string, any>, marker, idx) => {
                        acc[`billing-period-${idx}`] = {
                            type: 'line',
                            xMin: marker.date.utc().format('YYYY-MM-DD'),
                            xMax: marker.date.utc().format('YYYY-MM-DD'),
                            borderColor: isDarkModeOn ? 'rgba(255, 255, 255, 0.4)' : 'rgba(0, 0, 0, 0.4)',
                            borderWidth: 2,
                            borderDash: [8, 4],
                        }
                        return acc
                    }, {}),
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

            // Track chart dimensions for positioning
            const chartInstance = chartRef.current
            setChartDimensions({
                width: chartInstance.width,
                height: chartInstance.height,
            })
            setChartReady(true)
            const currentChartAreaLeft = chartInstance.chartArea?.left

            // Only show markers if chart area has stabilized
            if (stableChartAreaLeft !== null && Math.abs(currentChartAreaLeft - stableChartAreaLeft) < 1) {
                setMarkersReady(true)
            } else {
                setStableChartAreaLeft(currentChartAreaLeft)
                setMarkersReady(false)

                // Clear any existing timeout
                if (markerTimeoutRef.current) {
                    clearTimeout(markerTimeoutRef.current)
                }
                // Delay marker visibility to allow chart to stabilize
                markerTimeoutRef.current = setTimeout(() => {
                    setMarkersReady(true)
                }, 200)
            }
        }

        return () => {
            if (markerTimeoutRef.current) {
                clearTimeout(markerTimeoutRef.current)
            }
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
                setChartReady(false)
                setMarkersReady(false)
                setStableChartAreaLeft(null)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
        // Note: stableChartAreaLeft is intentionally excluded from dependencies to prevent re-render loops
        // since it's updated inside this useEffect itself
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
        billingPeriodMarkers,
    ])

    return (
        <div className="relative h-96" onMouseLeave={hideBillingTooltip}>
            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-bg-light bg-opacity-75 z-10">
                    <div className="text-muted">Loading...</div>
                </div>
            )}
            <canvas ref={canvasRef} />
            {/* Billing period marker overlays with tooltips */}
            {chartReady && markersReady && billingPeriodMarkers.length > 0 && (
                <div
                    className="BillingMarkersOverlay"
                    style={
                        {
                            '--billing-markers-chart-area-left': `${chartAreaLeft}px`,
                            '--billing-markers-chart-area-top': `${chartAreaTop}px`,
                            '--billing-marker-text-color': axisLabelColor,
                            '--billing-marker-bg-color': 'var(--color-bg-surface-primary)',
                            '--billing-marker-border-color': 'var(--color-border-primary)',
                        } as React.CSSProperties & Record<string, string>
                    }
                >
                    {billingPeriodMarkers
                        .filter((marker) => getMarkerPosition(marker.date).visible)
                        .slice(-1) // Show only the most recent visible marker
                        .map((marker, idx) => {
                            const position = getMarkerPosition(marker.date)

                            return (
                                <div
                                    key={`marker-${idx}`}
                                    className="BillingMarker"
                                    style={
                                        {
                                            '--billing-marker-left': `${position.left}px`,
                                        } as React.CSSProperties & Record<string, string>
                                    }
                                    onMouseEnter={hideBillingTooltip}
                                >
                                    <Tooltip
                                        title={
                                            <div className="p-2">
                                                <strong>New billing period started</strong>
                                                <p className="mt-2 text-xs">
                                                    Pricing tiers reset when billing periods begin, which can cause
                                                    temporary usage and spend changes:
                                                </p>
                                                <ul className="mt-1 text-xs list-disc list-inside">
                                                    <li>
                                                        Usage may drop to zero in last days of the billing period after
                                                        billing limits are reached
                                                    </li>
                                                    <li>Zero spend in first days due to free tier allowance</li>
                                                    <li>
                                                        Higher daily spend in first days due to higher rates at lower
                                                        volume tiers
                                                    </li>
                                                </ul>
                                            </div>
                                        }
                                        placement="bottom"
                                    >
                                        <div className="BillingMarkerLabel">
                                            New billing period
                                            <IconInfo className="w-3 h-3" />
                                        </div>
                                    </Tooltip>
                                </div>
                            )
                        })}
                </div>
            )}
        </div>
    )
}
