import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { dataVisualizationLogic } from '../../../dataVisualizationLogic'
import { ScatterPoint, buildScatterData } from './scatterUtils'

const NO_ROWS: any[] = []

export function ScatterPlot(): JSX.Element {
    const { response, columns, chartSettings, isDarkModeOn } = useValues(dataVisualizationLogic)

    const scatterSettings = chartSettings.scatter ?? {}
    const { xAxisColumn, yAxisColumn, labelColumn, xLogScale, yLogScale } = scatterSettings

    const rows =
        response && 'results' in response
            ? response.results
            : response && 'result' in response
              ? response.result
              : NO_ROWS
    const columnIndexes = useMemo(() => {
        return columns.reduce(
            (acc, column) => {
                acc[column.name] = column.dataIndex
                return acc
            },
            {} as Record<string, number>
        )
    }, [columns])

    const hasValidColumns =
        Boolean(xAxisColumn && yAxisColumn) &&
        columnIndexes[xAxisColumn ?? ''] !== undefined &&
        columnIndexes[yAxisColumn ?? ''] !== undefined

    const scatterData = useMemo(() => {
        if (!hasValidColumns) {
            return { points: [], skippedRowCount: 0 }
        }

        return buildScatterData(rows, { xAxisColumn, yAxisColumn, labelColumn, xLogScale, yLogScale }, columnIndexes)
    }, [rows, hasValidColumns, xAxisColumn, yAxisColumn, labelColumn, xLogScale, yLogScale, columnIndexes])

    const xAxisLabel = scatterSettings.xAxisLabel || xAxisColumn || 'X-axis'
    const yAxisLabel = scatterSettings.yAxisLabel || yAxisColumn || 'Y-axis'

    // useChart JSON.stringifies its deps on every render; a revision number keeps that O(1)
    // instead of serializing every point
    const chartRevisionRef = useRef(0)
    const chartRevision = useMemo(() => ++chartRevisionRef.current, [scatterData])

    const { canvasRef } = useChart<'scatter'>({
        getConfig: () => {
            return {
                type: 'scatter',
                data: {
                    datasets: [
                        {
                            data: scatterData.points,
                            backgroundColor: getSeriesColor(0),
                            pointRadius: 4,
                            pointHoverRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            callbacks: {
                                title: (context) => (context[0]?.raw as ScatterPoint)?.label ?? '',
                                label: (context) => {
                                    const point = context.raw as ScatterPoint
                                    return [
                                        `${xAxisLabel}: ${point.x.toLocaleString()}`,
                                        `${yAxisLabel}: ${point.y.toLocaleString()}`,
                                    ]
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            type: xLogScale ? 'logarithmic' : 'linear',
                            position: 'bottom',
                            title: {
                                display: true,
                                text: xAxisLabel,
                            },
                        },
                        y: {
                            type: yLogScale ? 'logarithmic' : 'linear',
                            title: {
                                display: true,
                                text: yAxisLabel,
                            },
                        },
                    },
                },
            }
        },
        // isDarkModeOn: getSeriesColor reads theme CSS variables, so a theme change must rebuild the chart
        deps: [chartRevision, xAxisLabel, yAxisLabel, xLogScale, yLogScale, isDarkModeOn],
    })

    if (!hasValidColumns) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState
                    heading="Select columns to build a scatter plot"
                    detail="Choose numeric X-axis and Y-axis columns to render the scatter plot."
                />
            </div>
        )
    }

    if (scatterData.points.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState heading="No data for selected columns" detail="" />
            </div>
        )
    }

    return (
        <div className="flex flex-col flex-1 gap-2 p-2 h-full">
            {scatterData.skippedRowCount > 0 && (
                <LemonBanner type="warning">
                    {`${scatterData.skippedRowCount} row${
                        scatterData.skippedRowCount === 1 ? ' was' : 's were'
                    } skipped because the X or Y value is missing or not numeric${
                        xLogScale || yLogScale ? ', or not positive on a logarithmic scale' : ''
                    }.`}
                </LemonBanner>
            )}
            <div className="relative flex-1 min-h-[300px]">
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}
