import clsx from 'clsx'
import { useCallback } from 'react'

import { DefaultTooltip, TimeSeriesLineChart, type PointClickData, type TooltipContext } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta, buildLineChartConfig, formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { useSqlChartModel, useSqlDateRangeZoom } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-line-chart')

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles line, area, goal
 * lines, and trend lines; everything else falls back to the legacy chart.js path. Tooltip content
 * (per-column formatting, total row) is configured in {@link buildLineChartConfig}.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element => {
    const { onPointClick: onPointClickProp } = props
    const model = useSqlChartModel(props, buildLineChartConfig)
    const onDateRangeZoom = useSqlDateRangeZoom(props)

    const onPointClick = useCallback(
        (data: PointClickData<SqlLineSeriesMeta>) => {
            onPointClickProp?.(data.series.key, data.dataIndex, data.label)
        },
        [onPointClickProp]
    )

    // When a click handler is wired, override the config-driven tooltip with a render prop so we
    // can add the inspect hint and sort by value. We pull the formatters off the built config to
    // avoid duplicating the per-column formatting logic.
    const renderTooltip = useCallback(
        (ctx: TooltipContext<SqlLineSeriesMeta>) => {
            if (!model) {
                return null
            }
            const { valueFormatter, labelFormatter, showTotal, totalFormatter } = model.config.tooltip ?? {}
            return (
                <DefaultTooltip
                    {...ctx}
                    valueFormatter={
                        valueFormatter ??
                        ((value, entry) =>
                            formatSqlSeriesValue(value, (entry.series.meta as SqlLineSeriesMeta | undefined)?.settings))
                    }
                    labelFormatter={labelFormatter}
                    showTotal={showTotal}
                    totalFormatter={totalFormatter}
                    sortedByValue
                    footer="Click to inspect persons"
                />
            )
        },
        [model]
    )

    return (
        <div
            className={clsx(
                props.className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col',
                { 'h-[60vh]': props.presetChartHeight, 'h-full': !props.presetChartHeight }
            )}
        >
            {model && (
                <TimeSeriesLineChart<SqlLineSeriesMeta>
                    series={model.series}
                    labels={model.labels}
                    theme={model.theme}
                    config={model.config}
                    tooltip={onPointClickProp ? renderTooltip : undefined}
                    onPointClick={onPointClickProp ? onPointClick : undefined}
                    onDateRangeZoom={onDateRangeZoom}
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
