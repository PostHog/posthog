import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { Chart } from 'lib/Chart'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { DailyRowsSyncedData, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseSourceIcon } from './settings/DataWarehouseSourceIcon'

const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
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
        },
    },
    scales: {
        x: {
            grid: { color: 'rgba(17, 24, 39, 0.08)', lineWidth: 0.5 },
            ticks: { maxTicksLimit: 8, color: '#6b7280', padding: 8 },
            border: { display: false },
        },
        y: {
            beginAtZero: true,
            grid: { color: 'rgba(17, 24, 39, 0.08)', lineWidth: 0.5 },
            ticks: { color: '#6b7280', padding: 8, maxTicksLimit: 6 },
            border: { display: false },
        },
    },
    interaction: { intersect: false, mode: 'index' as const },
    elements: { point: { hoverRadius: 8, hoverBorderWidth: 3 } },
    animation: { duration: 1000, easing: 'easeOutQuart' as const },
    hover: { mode: 'index' as const, intersect: false },
    layout: { padding: 20 },
}

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

        const options = {
            ...chartOptions,
            onClick: (_: any, elements: any[]) => {
                if (elements.length > 0) {
                    const { index } = elements[0]
                    onPointClick(data[index].date, data[index].rows_synced)
                }
            },
            plugins: {
                ...chartOptions.plugins,
                tooltip: {
                    ...chartOptions.plugins.tooltip,
                    callbacks: {
                        title: (context: any) => dayjs(data[context[0].dataIndex].date).format('MMM D, YYYY'),
                        label: (context: any) =>
                            context.parsed.y === null ? 'No data' : `${context.parsed.y} rows synced`,
                    },
                },
            },
        }

        chartRef.current = new Chart(canvasRef.current, {
            type: 'line',
            data: {
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
                    },
                ],
            },
            options,
        })

        return () => chartRef.current?.destroy()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data])

    return <canvas ref={canvasRef} />
}

export function DataWarehouseRowsSyncedGraph(): JSX.Element {
    const {
        dailyRowsSyncedData,
        hasData,
        dailyBreakdownDataLoading,
        selectedDate,
        selectedRows,
        activitySummary,
        modalTitle,
    } = useValues(dataWarehouseSceneLogic)
    const { setSelectedDate, setSelectedRows } = useActions(dataWarehouseSceneLogic)

    const handlePointClick = useCallback(
        (date: string, rows: number | null) => {
            setSelectedDate(date)
            setSelectedRows(rows)
        },
        [setSelectedDate, setSelectedRows]
    )

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

            <LemonModal isOpen={!!selectedDate} onClose={() => setSelectedDate(null)} title={modalTitle} width={600}>
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
                                                {Object.entries(activitySummary.runsBySource).map(([source, data]) => (
                                                    <div
                                                        key={source}
                                                        className="flex items-center justify-between p-3 bg-bg-light rounded border"
                                                    >
                                                        <div className="flex-1">
                                                            <div className="font-medium text-default">{source}</div>
                                                            <div className="text-sm text-muted">
                                                                {(data as any).schemas.join(', ')}
                                                            </div>
                                                        </div>
                                                        <div className="text-sm text-muted flex items-center gap-3">
                                                            <span>{(data as any).count} jobs</span>
                                                            <span>• {(data as any).rows} rows</span>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {activitySummary.timeSpanMinutes > 0 && (
                                        <div className="text-center text-sm text-muted-alt">
                                            Sync activity spanned {activitySummary.timeSpanMinutes} minutes
                                        </div>
                                    )}

                                    {activitySummary.runs.length > 0 && (
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
                                                            />
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
