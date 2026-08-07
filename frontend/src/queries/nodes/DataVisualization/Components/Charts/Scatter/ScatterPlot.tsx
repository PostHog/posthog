import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'
import { ScatterChart, useChartTheme } from '@posthog/quill-charts'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { dataVisualizationLogic } from '../../../dataVisualizationLogic'
import { buildScatterData, describeSkippedRows } from './scatterUtils'

const NO_ROWS: any[] = []
const handleChartError = makeChartErrorHandler('sql-scatter-chart')

export function ScatterPlot(): JSX.Element {
    const { response, columns, chartSettings } = useValues(dataVisualizationLogic)
    const theme = useChartTheme()

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

    const config = useMemo(
        () => ({ xLogScale, yLogScale, xAxisLabel, yAxisLabel }),
        [xLogScale, yLogScale, xAxisLabel, yAxisLabel]
    )

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

    const skippedRowsMessage = describeSkippedRows(scatterData.skippedRowCount, Boolean(xLogScale || yLogScale))

    if (scatterData.points.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState heading="No data for selected columns" detail={skippedRowsMessage} />
            </div>
        )
    }

    return (
        <div className="flex flex-col flex-1 gap-2 p-2 h-full">
            {skippedRowsMessage && <LemonBanner type="warning">{skippedRowsMessage}</LemonBanner>}
            <div className="relative flex-1 min-h-[300px]">
                <ScatterChart points={scatterData.points} theme={theme} config={config} onError={handleChartError} />
            </div>
        </div>
    )
}
