import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonBanner, LemonModal, Link } from '@posthog/lemon-ui'

import { Color, GridLineOptions, TickOptions } from 'lib/Chart'
import { getGraphColors } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'
import { hexToRGBA } from 'lib/utils/colors'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ScatterSettings } from '~/queries/schema/schema-general'

import { Column, dataVisualizationLogic } from '../../../dataVisualizationLogic'
import { ScatterPoint, buildScatterChartData } from './scatterChartAdapter'

const axisFont = {
    family: '"Emoji Flags Polyfill", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
    size: 12,
    weight: 'normal' as const,
}

const formatCellValue = (value: unknown): string => {
    if (value === null || value === undefined) {
        return 'null'
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

function ScatterRowModal({
    row,
    columns,
    personColumn,
    onClose,
}: {
    row: any[] | null
    columns: Column[]
    personColumn: string | null | undefined
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal isOpen={row !== null} onClose={onClose} title="Row details" width={480}>
            {row && (
                <div className="flex flex-col gap-2">
                    {columns.map((column) => {
                        const value = row[column.dataIndex]
                        const isPersonLink = personColumn === column.name && value !== null && value !== undefined
                        return (
                            <div key={column.name} className="flex justify-between gap-4">
                                <span className="text-secondary shrink-0">{column.name}</span>
                                {isPersonLink ? (
                                    <Link to={urls.personByDistinctId(String(value))}>{String(value)}</Link>
                                ) : (
                                    <span className="font-mono break-all text-right">{formatCellValue(value)}</span>
                                )}
                            </div>
                        )
                    })}
                </div>
            )}
        </LemonModal>
    )
}

export function SqlScatterGraph({ className }: { className?: string }): JSX.Element {
    const { response, columns, chartSettings } = useValues(dataVisualizationLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null)

    const scatterSettings: ScatterSettings = chartSettings.scatter ?? {}
    const rows: any[][] =
        response && 'results' in response ? response.results : response && 'result' in response ? response.result : []

    const chartData = useMemo(
        () => buildScatterChartData(rows ?? [], columns, scatterSettings),
        [rows, columns, scatterSettings]
    )

    const { canvasRef } = useChart<'scatter'>({
        getConfig: () => {
            if (!chartData || chartData.series.length === 0) {
                return null
            }

            const colors = getGraphColors()
            const tickOptions: Partial<TickOptions> = {
                color: colors.axisLabel as Color,
                font: axisFont,
            }
            const gridOptions: Partial<GridLineOptions> = {
                color: colors.axisLine as Color,
                tickColor: colors.axisLine as Color,
                tickBorderDash: [4, 2],
            }

            return {
                type: 'scatter',
                data: {
                    // Translucent borderless fills so overlapping dots compound into darker areas,
                    // reading as density; the hovered dot goes opaque to stand out.
                    datasets: chartData.series.map((series) => ({
                        label: series.label,
                        data: series.points,
                        backgroundColor: hexToRGBA(series.color, 0.45),
                        borderColor: series.color,
                        borderWidth: 0,
                        hoverBackgroundColor: series.color,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    })),
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'nearest', intersect: true },
                    onClick: (_event, elements) => {
                        const element = elements[0]
                        if (!element) {
                            return
                        }
                        const point = chartData.series[element.datasetIndex]?.points[element.index]
                        if (point) {
                            setSelectedRowIndex(point.rowIndex)
                        }
                    },
                    plugins: {
                        // The globally-registered crosshair plugin assumes an index axis; a scatter has none.
                        crosshair: false,
                        datalabels: { display: false },
                        legend: {
                            display: chartSettings.showLegend ?? Boolean(scatterSettings.colorByColumn),
                            labels: {
                                usePointStyle: true,
                                color: (colors.axisLabel as Color) ?? undefined,
                                font: axisFont,
                            },
                        },
                        tooltip: {
                            callbacks: {
                                title: (items) => {
                                    const raw = items[0]?.raw as ScatterPoint | undefined
                                    if (!raw) {
                                        return ''
                                    }
                                    return chartData.xIsDate
                                        ? dayjs(raw.x).format('YYYY-MM-DD HH:mm:ss')
                                        : String(raw.x)
                                },
                                label: (item) => {
                                    const raw = item.raw as ScatterPoint
                                    const row = rows[raw.rowIndex]
                                    if (!row) {
                                        return ''
                                    }
                                    return columns.map(
                                        (column) => `${column.name}: ${formatCellValue(row[column.dataIndex])}`
                                    )
                                },
                                footer: () => 'Click to inspect the row',
                            },
                        },
                    },
                    scales: {
                        x: {
                            type: chartData.xIsDate ? 'time' : 'linear',
                            ticks: tickOptions,
                            grid: gridOptions,
                            title: {
                                display: true,
                                text: scatterSettings.xAxisColumn ?? '',
                                color: (colors.axisLabel as Color) ?? undefined,
                                font: axisFont,
                            },
                        },
                        y: {
                            type: scatterSettings.yAxisScale === 'logarithmic' ? 'logarithmic' : 'linear',
                            ticks: tickOptions,
                            grid: gridOptions,
                            title: {
                                display: true,
                                text: scatterSettings.yAxisColumn ?? '',
                                color: (colors.axisLabel as Color) ?? undefined,
                                font: axisFont,
                            },
                        },
                    },
                },
            }
        },
        deps: [chartData, chartSettings.showLegend, scatterSettings, isDarkModeOn],
    })

    if (!scatterSettings.xAxisColumn || !scatterSettings.yAxisColumn || !chartData) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState
                    heading="Select columns to build a scatter plot"
                    detail="Choose an x-axis column and a numeric y-axis column to plot each row as a dot."
                />
            </div>
        )
    }

    if (chartData.series.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState heading="No plottable rows for the selected columns" detail="" />
            </div>
        )
    }

    const notes: string[] = []
    if (chartData.hiddenPointCount > 0) {
        notes.push(
            `${chartData.hiddenPointCount} row${chartData.hiddenPointCount === 1 ? '' : 's'} hidden (missing or non-numeric values${
                scatterSettings.yAxisScale === 'logarithmic' ? ', or non-positive values on a log scale' : ''
            })`
        )
    }
    if (chartData.truncated) {
        notes.push('Only the first 10,000 plottable rows are shown')
    }

    return (
        <div className={`flex flex-col h-full gap-2 p-3 ${className ?? ''}`}>
            {notes.length > 0 && <LemonBanner type="info">{notes.join('. ')}.</LemonBanner>}
            <div className="relative flex-1 min-h-0">
                <canvas ref={canvasRef} />
            </div>
            <ScatterRowModal
                row={selectedRowIndex !== null ? (rows[selectedRowIndex] ?? null) : null}
                columns={columns}
                personColumn={scatterSettings.personColumn}
                onClose={() => setSelectedRowIndex(null)}
            />
        </div>
    )
}
