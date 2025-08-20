import { actions, afterMount, kea, path, selectors, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { Chart, ChartDataset, ChartOptions } from 'lib/Chart'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { DataWarehouseDailyRowsBreakdown } from '~/types'

import type { dataWarehouseRowsSyncedGraphLogicType } from './DataWarehouseRowsSyncedGraphType'

export interface DailyRowsSyncedData {
    date: string
    rows_synced: number | null
}

const dataWarehouseRowsSyncedGraphLogic = kea<dataWarehouseRowsSyncedGraphLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseRowsSyncedGraphLogic']),
    actions({
        loadDailyBreakdown: true,
    }),
    loaders(() => ({
        dailyBreakdownData: [
            null as DataWarehouseDailyRowsBreakdown | null,
            {
                loadDailyBreakdown: async () => {
                    return await api.dataWarehouse.breakdownOfRowsSyncedByDayInBillingPeriod()
                },
            },
        ],
    })),
    selectors({
        dailyRowsSyncedData: [
            (s: any) => [s.dailyBreakdownData],
            (dailyBreakdownData: DataWarehouseDailyRowsBreakdown | null): DailyRowsSyncedData[] => {
                if (!dailyBreakdownData?.billing_available) {
                    return []
                }

                const billingStart = dayjs(dailyBreakdownData.billing_period_start)
                const billingEnd = dayjs(dailyBreakdownData.billing_period_end)
                const today = dayjs()

                if (!billingStart.isValid() || !billingEnd.isValid()) {
                    return []
                }

                const dailyData = new Map<string, number | null>()

                // Initialize all days in billing period
                let currentDate = billingStart
                while (currentDate.isSameOrBefore(billingEnd, 'day')) {
                    // Set future dates to null instead of 0
                    const isFutureDate = currentDate.isAfter(today, 'day')
                    dailyData.set(currentDate.format('YYYY-MM-DD'), isFutureDate ? null : 0)
                    currentDate = currentDate.add(1, 'day')
                }

                // Add actual data for past dates
                if (dailyBreakdownData.breakdown_of_rows_by_day) {
                    dailyBreakdownData.breakdown_of_rows_by_day.forEach(({ date, rows_synced }) => {
                        const dateObj = dayjs(date)
                        if (dateObj.isSameOrBefore(today, 'day')) {
                            dailyData.set(date, rows_synced)
                        }
                    })
                }

                return Array.from(dailyData.entries())
                    .map(([date, rows_synced]) => ({ date, rows_synced }))
                    .sort((a) => dayjs(a.date).unix() - dayjs(a.date).unix())
            },
        ],
        hasData: [
            (s: any) => [s.dailyRowsSyncedData],
            (dailyData: DailyRowsSyncedData[]): boolean =>
                dailyData.some((item) => item.rows_synced && item.rows_synced > 0),
        ],
        totalRowsInPeriod: [
            (s: any) => [s.dailyRowsSyncedData],
            (dailyData: DailyRowsSyncedData[]): number =>
                dailyData.reduce((sum, item) => sum + (item.rows_synced || 0), 0),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDailyBreakdown()
    }),
])

function SimpleLineChart({
    data,
    onPointClick,
}: {
    data: DailyRowsSyncedData[]
    onPointClick: (date: string, rows: number | null) => void
}): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<any>(null)

    const formatRows = (value: number): string => {
        if (value === 0) {
            return '0'
        }
        if (value < 1000) {
            return value.toLocaleString()
        }
        if (value < 1000000) {
            return `${(value / 1000).toFixed(1)}K`
        }
        return `${(value / 1000000).toFixed(1)}M`
    }

    useEffect(() => {
        if (!canvasRef.current || !data.length) {
            return
        }

        if (chartRef.current) {
            chartRef.current.destroy()
        }

        const chartData = {
            labels: data.map((d) => dayjs(d.date).format('MMM D')),
            datasets: [
                {
                    label: 'Rows synced',
                    data: data.map((d) => d.rows_synced),
                    borderColor: '#111827',
                    borderWidth: 2,
                    pointRadius: 6,
                    pointHoverRadius: 8,
                    pointBackgroundColor: '#111827',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 2,
                    tension: 0, // Remove curves - straight lines between points
                    fill: false,
                    spanGaps: true,
                    pointHitRadius: 10,
                    pointHoverBackgroundColor: '#ffffff',
                    pointHoverBorderColor: '#111827',
                } as ChartDataset<'line'>,
            ],
        }

        const options: ChartOptions<'line'> = {
            responsive: true,
            maintainAspectRatio: false,
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    const element = elements[0]
                    const dataIndex = element.index
                    const date = data[dataIndex].date
                    const rows = data[dataIndex].rows_synced
                    onPointClick(date, rows)
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    titleColor: '#ffffff',
                    bodyColor: '#ffffff',
                    borderColor: '#111827',
                    borderWidth: 1,
                    cornerRadius: 12,
                    displayColors: false,
                    padding: 12,
                    callbacks: {
                        title: (context) => dayjs(data[context[0].dataIndex].date).format('MMM D, YYYY'),
                        label: (context) => {
                            const value = context.parsed.y
                            return value === null ? 'No data' : `${formatRows(value)} rows synced`
                        },
                    },
                },
            },
            scales: {
                x: {
                    display: true,
                    grid: {
                        display: true,
                        color: 'rgba(17, 24, 39, 0.08)',
                        lineWidth: 0.5,
                    },
                    ticks: {
                        maxTicksLimit: 8,
                        color: '#6b7280',
                        padding: 8,
                    },
                    border: { display: false },
                },
                y: {
                    display: true,
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(17, 24, 39, 0.08)',
                        lineWidth: 0.5,
                    },
                    ticks: {
                        callback: (value) => (value === null ? '' : formatRows(value as number)),
                        color: '#6b7280',
                        padding: 8,
                        maxTicksLimit: 6,
                    },
                    border: { display: false },
                },
            },
            interaction: {
                intersect: false,
                mode: 'index',
            },
            elements: {
                point: {
                    hoverRadius: 8,
                    hoverBorderWidth: 3,
                },
            },
            animation: {
                duration: 1000,
                easing: 'easeOutQuart',
            },
            hover: {
                mode: 'index',
                intersect: false,
            },
            layout: {
                padding: {
                    top: 20,
                    right: 20,
                    bottom: 20,
                    left: 20,
                },
            },
        }

        chartRef.current = new Chart(canvasRef.current, {
            type: 'line',
            data: chartData,
            options,
        })

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
            }
        }
    }, [data, onPointClick])

    return <canvas ref={canvasRef} />
}

export function DataWarehouseRowsSyncedGraph(): JSX.Element {
    const { dailyRowsSyncedData, hasData, dailyBreakdownDataLoading } = useValues(dataWarehouseRowsSyncedGraphLogic)
    const [selectedDate, setSelectedDate] = useState<string | null>(null)
    const [selectedRows, setSelectedRows] = useState<number | null>(null)

    // Memoize the click handler to prevent re-renders
    const handlePointClick = useCallback((date: string, rows: number | null) => {
        setSelectedDate(date)
        setSelectedRows(rows)
    }, [])

    const formatRows = (value: number): string => {
        if (value === 0) {
            return '0'
        }
        if (value < 1000) {
            return value.toLocaleString()
        }
        if (value < 1000000) {
            return `${(value / 1000).toFixed(1)}K`
        }
        return `${(value / 1000000).toFixed(1)}M`
    }

    return (
        <>
            <div className="bg-white rounded-lg border border-border shadow-sm">
                <div className="p-4 border-b border-border">
                    <div>
                        <h3 className="text-xl font-semibold text-default">Daily Rows Synced</h3>
                        {hasData && (
                            <div className="text-sm text-muted">
                                Rows synced to your data warehouse over your current billing period.
                            </div>
                        )}
                    </div>
                </div>

                <div className="p-4">
                    {dailyBreakdownDataLoading ? (
                        <div className="h-64 flex items-center justify-center">
                            <div className="text-muted">Loading data...</div>
                        </div>
                    ) : !hasData ? (
                        <div className="h-64 flex items-center justify-center">
                            <div className="text-center">
                                <div className="text-muted-alt mb-2">No data synced yet.</div>
                                <div className="text-muted text-sm">
                                    Sync jobs will appear here once your data sources start syncing.
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="h-64">
                            <SimpleLineChart data={dailyRowsSyncedData} onPointClick={handlePointClick} />
                        </div>
                    )}
                </div>
            </div>

            <LemonModal
                isOpen={!!selectedDate}
                onClose={() => setSelectedDate(null)}
                title={`Sync Details for ${selectedDate ? dayjs(selectedDate).format('MMM D, YYYY') : ''}`}
                footer={
                    <div className="flex justify-end">
                        <button
                            onClick={() => setSelectedDate(null)}
                            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                        >
                            Close
                        </button>
                    </div>
                }
            >
                <div className="p-6">
                    {selectedRows === null ? (
                        <div className="text-center">
                            <div className="text-lg text-gray-600 mb-2">
                                No sync activity on {selectedDate ? dayjs(selectedDate).format('MMM D, YYYY') : ''}
                            </div>
                            <div className="text-sm text-gray-500">This date is in the future or has no sync jobs.</div>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="text-center">
                                <div className="text-3xl font-bold text-gray-900 mb-2">{formatRows(selectedRows)}</div>
                                <div className="text-lg text-gray-600">
                                    rows synced on {selectedDate ? dayjs(selectedDate).format('MMM D, YYYY') : ''}
                                </div>
                            </div>

                            <div className="border-t pt-4">
                                <div className="text-sm text-gray-500 mb-2">Sync Details:</div>
                                <div className="space-y-2 text-sm">
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Date:</span>
                                        <span className="font-medium">
                                            {selectedDate ? dayjs(selectedDate).format('MMM D, YYYY') : ''}
                                        </span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Rows Processed:</span>
                                        <span className="font-medium">{formatRows(selectedRows)}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Status:</span>
                                        <span className="font-medium text-green-600">Completed</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
