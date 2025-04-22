import './BillingUsage.scss'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
} from '@posthog/lemon-ui'
import { Chart, ChartDataset, ChartOptions } from 'chart.js'
import { useActions, useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { useEffect, useRef, useState } from 'react'

import { billingUsageLogic } from './billingUsageLogic'

const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Feature Flags', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Persons', value: 'enhanced_persons_event_count_in_period' },
]

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
    id: number
    label: string
    data: number[]
    days: string[]
    count: number
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

export function BillingUsage(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'usage' })
    const { series, dates, filters, dateFrom, dateTo, billingUsageResponseLoading } = useValues(logic)
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
            setHiddenSeries(series.map((s) => s.id))
        } else {
            // Show all series
            setHiddenSeries([])
        }
    }

    // Get date columns for the table - show all dates
    const getDateColumns = (): LemonTableColumn<SeriesType, keyof SeriesType | undefined>[] => {
        if (!dates || dates.length === 0) {
            return []
        }

        // Show all dates chronologically
        return dates.map((date, colIndex) => {
            const dateIndex = colIndex // This matches the index in the data array
            return {
                title: dayjs(date).format('MMM D'),
                render: (_, record: SeriesType) => {
                    return (
                        <div className="text-right">
                            {dateIndex >= 0 && dateIndex < record.data.length
                                ? record.data[dateIndex].toLocaleString()
                                : 0}
                        </div>
                    )
                },
                key: `date-${colIndex}`,
                sorter: (a: SeriesType, b: SeriesType) => {
                    return (a.data[dateIndex] || 0) - (b.data[dateIndex] || 0)
                },
                align: 'right', // Right-align the column header to match the data
            }
        })
    }

    // Define the total column
    const totalColumn: LemonTableColumn<SeriesType, keyof SeriesType | undefined> = {
        title: 'Total',
        render: (_, record: SeriesType) => (
            <div className="text-right font-semibold">
                {record.count
                    ? record.count.toLocaleString()
                    : record.data.reduce((sum, val) => sum + val, 0).toLocaleString()}
            </div>
        ),
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
        totalColumn, // Put the Total column right after Series
        ...getDateColumns(),
    ]

    return (
        <div className="space-y-4">
            <h2>Usage Details (Custom Graph)</h2>

            <div className="flex gap-2 items-center flex-wrap">
                <LemonSelect
                    value={filters.usage_type}
                    options={USAGE_TYPES}
                    onChange={(value) => setFilters({ usage_type: value || undefined })}
                    placeholder="Select usage type"
                    allowClear={true}
                />
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
                >
                    Compare
                </LemonButton>
            </div>

            {!filters.usage_type && !filters.breakdowns?.includes('type') && (
                <LemonBanner type="info">
                    Please select a usage type or break down by type to see usage data. Unselecting usage type will show
                    all types when you have a breakdown by type.
                </LemonBanner>
            )}

            {(filters.usage_type || filters.breakdowns?.includes('type')) && (
                <>
                    <div className="border rounded p-4 bg-white">
                        <BillingLineGraph
                            series={series}
                            dates={dates}
                            isLoading={billingUsageResponseLoading}
                            hiddenSeries={hiddenSeries}
                        />
                    </div>

                    {series.length > 0 && (
                        <div className="mt-4">
                            <h3 className="text-lg font-semibold mb-2">Detailed Results</h3>
                            <div className="overflow-x-auto border rounded">
                                <LemonTable
                                    dataSource={series}
                                    columns={columns}
                                    loading={billingUsageResponseLoading}
                                    className="bg-white"
                                    embedded
                                    size="small"
                                    rowClassName={(record) => (hiddenSeries.includes(record.id) ? 'opacity-50' : '')}
                                />
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
