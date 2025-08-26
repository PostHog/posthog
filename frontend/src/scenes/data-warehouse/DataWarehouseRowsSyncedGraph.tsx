import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { Chart } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { IconHandClick } from 'lib/lemon-ui/icons'
import { ensureTooltip, hideTooltip } from 'scenes/insights/views/LineGraph/LineGraph'
import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseDailyRowsSyncedData } from '~/types'

import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseSourceIcon } from './settings/DataWarehouseSourceIcon'

function DataWarehouseTooltip({
    date,
    rowsCount,
    timezone,
}: {
    date: string
    rowsCount: number | null
    timezone: string
}): JSX.Element {
    const formattedDate = dayjs(date).tz(timezone).format('MMM DD, YYYY')
    const timezoneAbbr = dayjs().tz(timezone).format('z')

    return (
        <div className="InsightTooltip">
            <div className="px-3 py-2 border-b border-border">
                <div className="text-xs text-muted-alt font-semibold">
                    {formattedDate} ({timezoneAbbr})
                </div>
            </div>
            <div className="px-3 py-2 border-b border-border">
                <div className="text-xs">
                    <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: getSeriesColor(0) }} />
                        <span className="font-semibold">
                            {rowsCount === null ? 'No data' : `${rowsCount.toLocaleString()} rows synced`}
                        </span>
                    </div>
                </div>
            </div>
            <div className="px-3 py-2">
                <div className="flex items-center justify-center gap-1 text-xs text-muted font-semibold">
                    <IconHandClick className="w-3 h-3" />
                    <span>Click to view details</span>
                </div>
            </div>
        </div>
    )
}

function SimpleLineChart({
    data,
    onPointClick,
    isModalOpen,
}: {
    data: DataWarehouseDailyRowsSyncedData[]
    onPointClick: (date: string, rows: number | null) => void
    isModalOpen: boolean
}): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)
    const { timezone } = useValues(teamLogic)

    useEffect(() => {
        if (!canvasRef.current || !data.length) {
            return
        }

        if (chartRef.current) {
            chartRef.current.destroy()
        }

        const colors = getGraphColors()
        const primaryColor = getSeriesColor(0)

        const options = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            onClick: (_: any, elements: any[]) => {
                if (elements.length > 0) {
                    const { index } = elements[0]
                    onPointClick(data[index].date, data[index].rows_synced)
                }
            },
            interaction: {
                mode: 'nearest' as const,
                axis: 'x' as const,
                intersect: false,
            },
            hover: {
                intersect: false,
            },
            onHover: (_: any, activeElements: any[]) => {
                if (activeElements.length === 0) {
                    hideTooltip()
                }
            },
            plugins: {
                legend: { display: false },
                crosshair: {
                    snap: {
                        enabled: true,
                    },
                    sync: {
                        enabled: false,
                    },
                    zoom: {
                        enabled: false,
                    },
                    line: {
                        color: colors.crosshair ?? undefined,
                        width: 1,
                    },
                },
                tooltip: {
                    enabled: false,
                    external: ({ chart, tooltip }: any) => {
                        if (!tooltip.body || isModalOpen) {
                            hideTooltip()
                            return
                        }
                        if (tooltip.opacity === 0) {
                            hideTooltip()
                            return
                        }

                        const [tooltipRoot, tooltipEl] = ensureTooltip()
                        const dataIndex = tooltip.dataPoints?.[0]?.dataIndex

                        if (dataIndex !== undefined && data[dataIndex]) {
                            const point = data[dataIndex]

                            tooltipRoot.render(
                                <DataWarehouseTooltip
                                    date={point.date}
                                    rowsCount={point.rows_synced}
                                    timezone={timezone}
                                />
                            )

                            const bounds = chart.canvas.getBoundingClientRect()
                            const chartClientLeft = bounds.left + window.pageXOffset
                            const tooltipClientTop = bounds.top + window.pageYOffset

                            const defaultOffsetLeft = Math.max(chartClientLeft, chartClientLeft + tooltip.caretX + 8)
                            const maxXPosition = bounds.right - tooltipEl.clientWidth
                            const tooltipClientLeft =
                                defaultOffsetLeft > maxXPosition
                                    ? chartClientLeft + tooltip.caretX - tooltipEl.clientWidth - 8
                                    : defaultOffsetLeft

                            tooltipEl.style.opacity = '1'
                            tooltipEl.style.position = 'absolute'
                            tooltipEl.style.left = tooltipClientLeft + 'px'
                            tooltipEl.style.top = tooltipClientTop + tooltip.caretY + 8 + 'px'
                        }
                    },
                },
            },
            scales: {
                x: {
                    grid: {
                        display: false,
                    },
                    ticks: {
                        color: colors.axisLabel || '#666666',
                        maxTicksLimit: 8,
                    },
                    border: { display: false },
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: colors.axisLine || 'rgba(0, 0, 0, 0.1)',
                    },
                    ticks: {
                        color: colors.axisLabel || '#666666',
                        maxTicksLimit: 6,
                        callback: function (value: any) {
                            return typeof value === 'number' ? value.toLocaleString() : value
                        },
                    },
                    border: { display: false },
                },
            },
            elements: {
                line: {
                    tension: 0,
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
                        borderColor: primaryColor,
                        backgroundColor: primaryColor,
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: primaryColor,
                        pointHoverBorderWidth: 2,
                        fill: false,
                        spanGaps: true,
                    },
                ],
            },
            options,
        })

        return () => chartRef.current?.destroy()
    }, [data, onPointClick, isModalOpen, timezone])

    return (
        <div className="h-full" onMouseLeave={hideTooltip}>
            <canvas ref={canvasRef} />
        </div>
    )
}

export function DataWarehouseRowsSyncedGraph(): JSX.Element {
    const {
        dailyRowsSyncedData,
        hasData,
        dailyBreakdownDataLoading,
        totalRowsInPeriod,
        selectedDate,
        selectedRows,
        selectedDateRunsBySource,
    } = useValues(dataWarehouseSceneLogic)
    const { setSelectedDate, setSelectedRows } = useActions(dataWarehouseSceneLogic)

    const handlePointClick = useCallback(
        (date: string, rows: number | null) => {
            hideTooltip()
            setSelectedDate(date)
            setSelectedRows(rows)
        },
        [setSelectedDate, setSelectedRows]
    )

    return (
        <div className="bg-white rounded-lg border border-border shadow-sm">
            <div className="p-4">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h3 className="text-xl font-semibold text-default">Daily Rows Synced</h3>
                        {hasData && (
                            <div className="text-sm text-muted">
                                {totalRowsInPeriod.toLocaleString()} total rows synced over your current billing period
                            </div>
                        )}
                    </div>
                </div>

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
                        <SimpleLineChart
                            data={dailyRowsSyncedData}
                            onPointClick={handlePointClick}
                            isModalOpen={!!selectedDate}
                        />
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={!!selectedDate}
                onClose={() => {
                    hideTooltip()
                    setSelectedDate('')
                }}
                title={null}
                width={560}
                simple
            >
                <LemonModal.Header>
                    <h3>Sync Activity on {selectedDate ? dayjs(selectedDate).format('MMMM D, YYYY') : ''}</h3>
                </LemonModal.Header>

                {selectedRows === null ? (
                    <div className="px-4 py-6">
                        <div className="text-center">
                            <div className="text-lg text-muted-alt mb-2">
                                No sync activity on {dayjs(selectedDate!).format('MMMM D, YYYY')}
                            </div>
                            <div className="text-sm text-muted">This date is in the future or has no sync jobs.</div>
                        </div>
                    </div>
                ) : (
                    <>
                        {selectedDateRunsBySource && selectedDateRunsBySource.length > 0 ? (
                            <>
                                <div className="flex items-center gap-2 text-secondary px-4 pt-2">
                                    <span>
                                        <b>{selectedRows.toLocaleString()} rows synced</b>
                                    </span>
                                </div>

                                <div className="px-4 py-2">
                                    <div className="space-y-2 mb-2">
                                        {selectedDateRunsBySource.map(({ source, count, rows }) => (
                                            <div key={source} className="flex items-center gap-2 text-sm">
                                                <span className="flex items-center gap-1">
                                                    <DataWarehouseSourceIcon type={source} size="xsmall" />
                                                    <span className="font-medium">{source}</span>
                                                </span>
                                                <span>
                                                    {rows.toLocaleString()} {rows === 1 ? 'row' : 'rows'} • {count}{' '}
                                                    {count === 1 ? 'job' : 'jobs'}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="px-4 overflow-hidden flex flex-col">
                                    <div className="relative min-h-20 p-2 deprecated-space-y-2 rounded bg-border-light overflow-y-auto mb-2">
                                        {selectedDateRunsBySource.flatMap(({ source, runs }) =>
                                            runs.map((run: any) => (
                                                <div
                                                    key={run.id}
                                                    className="flex items-center justify-between p-2 border rounded bg-white"
                                                >
                                                    <div className="flex items-center gap-2">
                                                        <DataWarehouseSourceIcon type={source} size="xsmall" />
                                                        <div>
                                                            <div className="font-medium text-sm">{run.schema_name}</div>
                                                            <div className="text-xs text-muted">
                                                                {run.rows_synced?.toLocaleString() || 0}{' '}
                                                                {run.rows_synced === 1 ? 'row' : 'rows'}
                                                            </div>
                                                        </div>
                                                    </div>
                                                    <div className="text-xs text-muted">
                                                        <TZLabel time={run.created_at} />
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div className="px-4 py-6">
                                <div className="text-center">
                                    <div className="text-lg font-semibold text-default mb-2">
                                        No sync data available
                                    </div>
                                    <div className="text-sm text-muted">
                                        {dayjs(selectedDate!).format('MMMM D, YYYY')} does not appear to have any data
                                        warehouse sync activity!
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </LemonModal>
        </div>
    )
}
