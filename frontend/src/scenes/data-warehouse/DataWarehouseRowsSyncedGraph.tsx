import { actions, afterMount, kea, path, selectors, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import { useEffect, useRef } from 'react'

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
                    .sort((a, b) => dayjs(a.date).unix() - dayjs(b.date).unix())
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
function SimpleLineChart({ data }: { data: DailyRowsSyncedData[] }): JSX.Element {
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
                    borderColor: '#111827', // Black line
                    borderWidth: 2, // Thicker line
                    pointRadius: 6, // Hide points by default
                    pointHoverRadius: 8, // Show points on hover
                    pointBackgroundColor: '#111827',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 2,
                    tension: 0.4, // Smooth curves
                    fill: false, // Enable fill
                    spanGaps: true,
                    pointHitRadius: 10, // Larger hover area
                    pointHoverBackgroundColor: '#ffffff',
                    pointHoverBorderColor: '#111827',
                } as ChartDataset<'line'>,
            ],
        }

        const options: ChartOptions<'line'> = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)', // Dark tooltip
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
                        color: 'rgba(17, 24, 39, 0.08)', // Very light grid
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
    }, [data])

    return <canvas ref={canvasRef} />
}

export function DataWarehouseRowsSyncedGraph(): JSX.Element {
    const { dailyRowsSyncedData, hasData, dailyBreakdownDataLoading } = useValues(dataWarehouseRowsSyncedGraphLogic)
    return (
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
                        <SimpleLineChart data={dailyRowsSyncedData} />
                    </div>
                )}
            </div>
        </div>
    )
}
