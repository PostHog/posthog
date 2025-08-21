import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { Chart, ChartDataset, ChartOptions } from 'lib/Chart'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { DailyRowsSyncedData, dataWarehouseRowsSyncedGraphLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseSourceIcon } from './settings/DataWarehouseSourceIcon'

function SimpleLineChart({
    data,
    onPointClick,
}: {
    data: DailyRowsSyncedData[]
    onPointClick: (date: string, rows: number | null) => void
}): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<any>(null)

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
                    tension: 0.3,
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
            onClick: (_event, elements) => {
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
                            return value === null ? 'No data' : `${value} rows synced`
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
                        callback: (value) => (value === null ? '' : (value as number)),
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
    const { dailyRowsSyncedData, hasData, dailyBreakdownDataLoading, selectedDate, selectedRows, activitySummary } =
        useValues(dataWarehouseRowsSyncedGraphLogic)
    const { setSelectedDate, setSelectedRows } = useActions(dataWarehouseRowsSyncedGraphLogic)

    const handlePointClick = (date: string, rows: number | null): void => {
        setSelectedDate(date)
        setSelectedRows(rows)
    }

    return (
        <>
            <div className="bg-white rounded-lg border border-border shadow-sm">
                <div className="p-2">
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
                title={selectedDate ? `Sync Activity - ${dayjs(selectedDate).format('MMM D, YYYY')}` : 'Sync Activity'}
                width={600}
            >
                <div className="space-y-6">
                    {selectedRows === null ? (
                        <div className="text-center py-8">
                            <div className="text-lg text-muted-alt mb-2">
                                No sync activity on {dayjs(selectedDate!).format('MMM D, YYYY')}
                            </div>
                            <div className="text-sm text-muted">This date is in the future or has no sync jobs.</div>
                        </div>
                    ) : (
                        <>
                            <div className="text-center border-b pb-6">
                                <div className="text-4xl font-bold text-default mb-2">{selectedRows}</div>
                                <div className="text-lg text-muted-alt">
                                    rows synced on {dayjs(selectedDate!).format('MMM D, YYYY')}
                                </div>
                            </div>

                            {activitySummary ? (
                                <div className="space-y-4">
                                    {activitySummary.hasMultipleSources && (
                                        <div>
                                            <h4 className="font-semibold mb-3">Sources</h4>
                                            <div className="space-y-2">
                                                {Object.entries(activitySummary.runsBySource).map(([source, data]) => {
                                                    const sourceData = data as {
                                                        count: number
                                                        rows: number
                                                        schemas: string[]
                                                    }
                                                    return (
                                                        <div
                                                            key={source}
                                                            className="flex items-center justify-between p-3 bg-bg-light rounded border"
                                                        >
                                                            <div className="flex-1">
                                                                <div className="font-medium text-default">{source}</div>
                                                                <div className="text-sm text-muted">
                                                                    {sourceData.schemas.join(', ')}
                                                                </div>
                                                            </div>
                                                            <div className="text-sm text-muted flex items-center gap-3">
                                                                <span>{sourceData.count} jobs</span>
                                                                <span>• {sourceData.rows} rows</span>
                                                            </div>
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        </div>
                                    )}

                                    {activitySummary.timeSpanMinutes > 0 && (
                                        <div className="text-center text-sm text-muted-alt">
                                            Sync activity spanned {activitySummary.timeSpanMinutes} minutes
                                        </div>
                                    )}

                                    {activitySummary.runs.length > 0 && (
                                        <div>
                                            <div className="space-y-3 max-h-64 overflow-y-auto">
                                                {activitySummary.runs.slice(0, 10).map((run: any) => (
                                                    <div
                                                        key={run.id}
                                                        className="flex items-center justify-between p-3 bg-bg-light rounded border"
                                                    >
                                                        <div className="flex-1">
                                                            <div className="font-medium text-default flex items-center gap-2">
                                                                <DataWarehouseSourceIcon
                                                                    type={run.source_type}
                                                                    size="xsmall"
                                                                />{' '}
                                                                {run.source_type} • {run.schema_name}
                                                            </div>
                                                            <div className="text-sm text-muted flex items-center gap-2">
                                                                <TZLabel time={run.created_at} />
                                                                <span>• {run.rows_synced} rows</span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <div className="text-center py-4">
                                    <div className="text-lg text-muted-alt mb-2">No sync data available</div>
                                    <div className="text-sm text-muted">
                                        This date may not have any data warehouse sync activity or the data may not be
                                        available yet.
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
