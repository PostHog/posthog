import clsx from 'clsx'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

import { BoxPlot } from '@posthog/quill-charts'
import type { BoxPlotConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { ChartSettings } from '~/queries/schema/schema-general'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { Column } from '../../dataVisualizationLogic'
import { buildSqlBoxPlotModel } from './sqlBoxPlotAdapter'

const handleChartError = makeChartErrorHandler('sql-box-plot')
const capturedUnrenderedItems = new Set<string>()

export interface SqlBoxPlotProps {
    rows: unknown[][]
    columns: Column[]
    chartSettings: ChartSettings
    analyticsKey: string
    presetChartHeight?: boolean
    className?: string
}

export const SqlBoxPlot = ({
    rows,
    columns,
    chartSettings,
    analyticsKey,
    presetChartHeight,
    className,
}: SqlBoxPlotProps): JSX.Element => {
    const theme = useChartTheme()
    const model = useMemo(
        () => buildSqlBoxPlotModel(rows, columns, chartSettings.boxPlot ?? {}),
        [rows, columns, chartSettings.boxPlot]
    )
    const skippedRowCount = Object.values(model.skippedRows).reduce((total, count) => total + count, 0)
    useEffect(() => {
        const chartSessionKey = `${analyticsKey}:${posthog.get_session_id?.() ?? 'unknown'}`
        if (skippedRowCount > 0 && !capturedUnrenderedItems.has(chartSessionKey)) {
            capturedUnrenderedItems.add(chartSessionKey)
            // pinned: analytics event name - renaming breaks dashboards
            posthog.capture('sql box plot items not rendered', {
                unrendered_item_count: skippedRowCount,
                total_item_count: rows.length,
                reasons: model.skippedRows,
            })
        }
    }, [analyticsKey, model.skippedRows, rows.length, skippedRowCount])

    const yAxisSettings = chartSettings.leftYAxisSettings
    const config = useChartConfig<BoxPlotConfig>(
        () => ({
            yScaleType: yAxisSettings?.scale === 'logarithmic' ? 'log' : 'linear',
            xAxisLabel: chartSettings.xAxisLabel,
            yAxisLabel: yAxisSettings?.label,
            hideXAxis: chartSettings.showXAxisTicks === false,
            hideYAxis: yAxisSettings?.showTicks === false,
            showGrid: yAxisSettings?.showGridLines ?? true,
            showAxisLines: {
                x: chartSettings.showXAxisBorder ?? true,
                y: chartSettings.showYAxisBorder ?? true,
            },
            tooltip: { pinnable: true, placement: 'cursor' },
            legend: { show: chartSettings.showLegend ?? false, position: 'top' },
        }),
        [chartSettings, yAxisSettings]
    )

    const heightClass = presetChartHeight ? 'h-[60vh]' : 'h-full'

    const containerClassName = clsx(
        className,
        'rounded bg-surface-primary flex flex-1 items-center justify-center p-3',
        heightClass
    )

    if (model.error) {
        return (
            <div className={containerClassName} data-attr="sql-box-plot-error">
                <span className="text-secondary text-sm">{model.error}</span>
            </div>
        )
    }

    if (model.series.length === 0) {
        return (
            <div className={containerClassName} data-attr="sql-box-plot-empty">
                <span className="text-secondary text-sm">No boxes to plot. Check that your query returns rows.</span>
            </div>
        )
    }

    return (
        <div
            className={clsx(
                className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col p-3',
                heightClass
            )}
        >
            <BoxPlot
                series={model.series}
                labels={model.labels}
                theme={theme}
                config={config}
                dataAttr="sql-box-plot"
                onError={handleChartError}
            />
        </div>
    )
}
