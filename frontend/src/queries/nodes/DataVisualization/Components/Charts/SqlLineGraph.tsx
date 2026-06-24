import clsx from 'clsx'

import { TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta, buildLineChartConfig } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-line-chart')

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles line, area, goal
 * lines, and trend lines; everything else falls back to the legacy chart.js path. Tooltip content
 * (per-column formatting, total row) is configured in {@link buildLineChartConfig}.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlChartModel(props, buildLineChartConfig)

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
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
