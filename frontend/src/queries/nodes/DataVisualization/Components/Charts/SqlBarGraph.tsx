import clsx from 'clsx'
import { useCallback } from 'react'

import { DefaultTooltip, TimeSeriesBarChart, type PointClickData, type TooltipContext } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { type SqlChartProps } from './SqlChart'
import { type SqlLineSeriesMeta, buildBarChartConfig, formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-bar-chart')

export const SqlBarGraph = (props: SqlChartProps): JSX.Element => {
    const { onPointClick: onPointClickProp } = props
    const model = useSqlChartModel(props, buildBarChartConfig)

    const onPointClick = useCallback(
        (data: PointClickData<SqlLineSeriesMeta>) => {
            onPointClickProp?.(data.series.key, data.dataIndex, data.label)
        },
        [onPointClickProp]
    )

    // When a click handler is wired, override the config-driven tooltip with a render prop so we can
    // add the click hint footer, reusing the built config's formatters. Mirrors SqlLineGraph.
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
                    footer={props.pointClickHint}
                />
            )
        },
        [model, props.pointClickHint]
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
                <TimeSeriesBarChart
                    series={model.series}
                    labels={model.labels}
                    theme={model.theme}
                    config={model.config}
                    tooltip={onPointClickProp ? renderTooltip : undefined}
                    onPointClick={onPointClickProp ? onPointClick : undefined}
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
