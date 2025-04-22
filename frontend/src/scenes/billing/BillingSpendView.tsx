import './BillingUsage.scss' // Keep existing styles for now

import {
    LemonButton,
    LemonCheckbox,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
} from '@posthog/lemon-ui'
import { Chart, ChartDataset, ChartOptions, TooltipItem } from 'chart.js' // Added TooltipItem
import { useActions, useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { useEffect, useRef, useState } from 'react'

import { billingSpendLogic } from './billingSpendLogic' // Use spend logic

// No usage types needed for spend
// const USAGE_TYPES = [...]

type BreakdownOption = { label: string; value: string | null }

const BREAKDOWN_OPTIONS: BreakdownOption[] = [
    { label: 'None', value: null },
    { label: 'By Type', value: 'type' },
    { label: 'By Team', value: 'team' },
    { label: 'By Type & Team', value: 'both' },
]

const INTERVAL_OPTIONS = [
    { label: 'Day', value: 'day' },
    { label: 'Week', value: 'week' },
    { label: 'Month', value: 'month' },
]

interface SeriesType {
    // Keep interface name for simplicity, data is now spend
    id: number
    label: string
    data: number[]
    days: string[]
    count: number // Still relevant? Maybe for total spend, keeping for now
    compare?: boolean
    compare_label?: string
    breakdown_value?: string | string[]
}

interface BillingLineGraphProps {
    series: SeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
}

// Component for color dot with the correct color
function SeriesColorDot({ colorIndex }: { colorIndex: number }): JSX.Element {
    // Set the color via CSS variable in a class
    return <div className={`series-color-dot series-color-dot-${colorIndex % 15}`} />
}

// Reusable graph component (mostly unchanged, added currency formatting)
function BillingLineGraph({ series, dates, isLoading, hiddenSeries }: BillingLineGraphProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    useEffect(() => {
        if (!canvasRef.current) {
            return
        }

        // Destroy existing chart if it exists
        if (chartRef.current) {
            chartRef.current.destroy()
        }

        // Filter series based on hidden state
        const visibleSeries = series.filter((s) => !hiddenSeries.includes(s.id))

        const datasets: ChartDataset<'line'>[] = visibleSeries.map((s) => ({
            label: s.label,
            data: s.data, // Data represents spend (e.g., in USD)
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
                    // Format Y-axis ticks as currency
                    ticks: {
                        callback: function (value) {
                            if (typeof value === 'number') {
                                return value.toLocaleString('en-US', {
                                    style: 'currency',
                                    currency: 'USD',
                                    maximumFractionDigits: 0, // No cents needed for ticks usually
                                })
                            }
                            return value
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
                            return dayjs(context[0].parsed.x).format('MMMM D, YYYY')
                        },
                        // Format tooltip values as currency
                        label: (context: TooltipItem<'line'>) => {
                            let label = context.dataset.label || ''
                            if (label) {
                                label += ': '
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y.toLocaleString('en-US', {
                                    style: 'currency',
                                    currency: 'USD',
                                })
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
    }, [series, dates, hiddenSeries])

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

// Renamed component to BillingSpendView
export function BillingSpendView(): JSX.Element {
    // Use spend logic
    const logic = billingSpendLogic({ dashboardItemId: 'spendView' }) // Updated key
    // Use spend response loading state
    const { series, dates, filters, dateFrom, dateTo, billingSpendResponseLoading } = useValues(logic)
    const { setFilters, setDateRange } = useActions(logic)
    const [hiddenSeries, setHiddenSeries] = useState<number[]>([])

    const handleBreakdownChange = (value: string | null): void => {
        if (!value) {
            setFilters({ breakdowns: undefined })
        } else if (value === 'both') {
            setFilters({ breakdowns: ['type', 'team'] })
        } else {
            setFilters({ breakdowns: [value] })
        }
    }

    // Function to toggle a series visibility by ID
    const toggleSeries = (id: number): void => {
        setHiddenSeries((prevHidden) =>
            prevHidden.includes(id) ? prevHidden.filter((i) => i !== id) : [...prevHidden, id]
        )
    }

    // Function to toggle all series visibility
    const toggleAllSeries = (): void => {
        if (hiddenSeries.length === 0 && series.length > 0) {
            // Hide all series
            setHiddenSeries(series.map((s: SeriesType) => s.id))
        } else {
            // Show all series
            setHiddenSeries([])
        }
    }

    // Get date columns for the table - adapt rendering for currency
    const getDateColumns = (): LemonTableColumn<SeriesType, keyof SeriesType | undefined>[] => {
        if (!dates || dates.length === 0) {
            return []
        }

        // Show all dates chronologically
        return dates.map((date: string, colIndex: number) => {
            const dateIndex = colIndex // This matches the index in the data array
            return {
                title: dayjs(date).format('MMM D'),
                render: (_: any, record: SeriesType) => {
                    const value = record.data[dateIndex]
                    return (
                        <div className="text-right">
                            {dateIndex >= 0 && dateIndex < record.data.length
                                ? value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
                                : '$0.00'}
                        </div>
                    )
                },
                key: `date-${colIndex}`,
                sorter: (a: SeriesType, b: SeriesType) => {
                    return (a.data[dateIndex] || 0) - (b.data[dateIndex] || 0)
                },
                align: 'right',
            }
        })
    }

    // Define the total column - adapt rendering for currency
    const totalColumn: LemonTableColumn<SeriesType, keyof SeriesType | undefined> = {
        title: 'Total Spend',
        render: (_, record: SeriesType) => {
            const total = record.count // Assuming backend provides total spend in count? Or sum data?
                ? record.count
                : record.data.reduce((sum, val) => sum + val, 0)
            return (
                <div className="text-right font-semibold">
                    {total.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                </div>
            )
        },
        key: 'total',
        sorter: (a: SeriesType, b: SeriesType) => {
            const totalA = a.count || a.data.reduce((sum, val) => sum + val, 0)
            const totalB = b.count || b.data.reduce((sum, val) => sum + val, 0)
            return totalA - totalB
        },
        align: 'right',
    }

    // Define table columns
    const columns: LemonTableColumns<SeriesType> = [
        {
            title: (
                <div className="flex items-center">
                    <LemonCheckbox
                        checked={series.length > 0 && hiddenSeries.length === 0}
                        onChange={toggleAllSeries}
                        className="mr-2"
                    />
                    <span>Series</span>
                </div>
            ),
            render: (_, record: SeriesType) => {
                const isHidden = hiddenSeries.includes(record.id)
                return (
                    <div className="flex items-center">
                        <LemonCheckbox checked={!isHidden} onChange={() => toggleSeries(record.id)} className="mr-2" />
                        <SeriesColorDot colorIndex={record.id} />
                        <span className="font-medium">{record.label}</span>
                    </div>
                )
            },
            key: 'series',
            sorter: (a: SeriesType, b: SeriesType) => a.label.localeCompare(b.label),
        },
        totalColumn,
        ...getDateColumns(),
    ]

    return (
        <div className="space-y-4">
            {/* Changed title */}
            <h2>Spend Details</h2>

            <div className="flex gap-2 items-center flex-wrap">
                {/* Removed Usage Type LemonSelect */}
                <LemonSelect<string | null>
                    value={filters.breakdowns?.length === 2 ? 'both' : filters.breakdowns?.[0] || null}
                    options={BREAKDOWN_OPTIONS}
                    onChange={handleBreakdownChange}
                    placeholder="Select breakdown"
                />
                <LemonSelect
                    value={filters.interval || 'day'}
                    options={INTERVAL_OPTIONS}
                    onChange={(value) => setFilters({ interval: value as 'day' | 'week' | 'month' })}
                />
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(fromDate, toDate) => setDateRange(fromDate || null, toDate || null)}
                />
                <LemonButton
                    type="secondary"
                    onClick={() => setFilters({ compare: filters.compare ? undefined : 'previous_period' })}
                    active={!!filters.compare}
                    // TODO: Verify if compare is supported for spend API
                    tooltip="Compare to previous period (if supported)"
                >
                    Compare
                </LemonButton>
            </div>

            {/* Removed banner related to usage type selection */}

            {/* Simplified condition, always show if logic is mounted */}
            <>
                <div className="border rounded p-4 bg-white">
                    <BillingLineGraph
                        series={series}
                        dates={dates}
                        isLoading={billingSpendResponseLoading} // Use spend loading state
                        hiddenSeries={hiddenSeries}
                    />
                </div>

                {series.length > 0 && (
                    <div className="mt-4">
                        <h3 className="text-lg font-semibold mb-2">Detailed Spend Results</h3> {/* Changed title */}
                        <div className="overflow-x-auto border rounded">
                            <LemonTable
                                dataSource={series}
                                columns={columns}
                                loading={billingSpendResponseLoading} // Use spend loading state
                                className="bg-white"
                                embedded
                                size="small"
                                rowClassName={(record) => (hiddenSeries.includes(record.id) ? 'opacity-50' : '')}
                            />
                        </div>
                    </div>
                )}
            </>
        </div>
    )
}
