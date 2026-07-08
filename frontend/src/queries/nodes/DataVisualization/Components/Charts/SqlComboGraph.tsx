import clsx from 'clsx'

import { TimeSeriesComboChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta, buildComboChartConfig } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-combo-chart')

/**
 * SQL mixed bar + line/area graph rendered via @posthog/quill-charts' {@link TimeSeriesComboChart},
 * gated behind the `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles the
 * mixed-type case the line-only and bar-only paths can't. Tooltip content (per-column formatting,
 * total row) is configured in {@link buildComboChartConfig}.
 */
export const SqlComboGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlChartModel(props, buildComboChartConfig)

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
                    dataAttr="sql-combo-graph"
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
