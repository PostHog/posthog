import clsx from 'clsx'
import { useCallback } from 'react'

import { DefaultTooltip, TimeSeriesComboChart, type TooltipContext } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta, buildComboChartConfig, formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-combo-chart')

/**
 * SQL mixed bar + line/area graph rendered via @posthog/quill-charts' {@link TimeSeriesComboChart},
 * gated behind the `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles the
 * mixed-type case the line-only and bar-only paths can't; the tooltip is quill's DefaultTooltip
 * extended to format each row with its column's own settings and show a total row.
 */
export const SqlComboGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlChartModel(props, buildComboChartConfig)
    const { chartSettings } = props
    const totalSettings = model?.totalFormatterSettings

    const showTotalRow = chartSettings.showTotalRow !== false

    const renderTooltip = useCallback(
        (ctx: TooltipContext<SqlLineSeriesMeta>): JSX.Element => (
            <DefaultTooltip<SqlLineSeriesMeta>
                {...ctx}
                valueFormatter={(value, entry) => formatSqlSeriesValue(value, entry.series.meta?.settings)}
                showTotal={showTotalRow}
                totalFormatter={(value) => formatSqlSeriesValue(value, totalSettings)}
            />
        ),
        [showTotalRow, totalSettings]
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
                <TimeSeriesComboChart<SqlLineSeriesMeta>
                    series={model.series}
                    labels={model.labels}
                    theme={model.theme}
                    config={model.config}
                    tooltip={renderTooltip}
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
