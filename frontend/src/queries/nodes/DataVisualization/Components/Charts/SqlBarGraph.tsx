import clsx from 'clsx'

import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { useSqlBarGraph } from './useSqlBarGraph'

const handleChartError = makeChartErrorHandler('sql-bar-chart')

/**
 * SQL bar / stacked-bar graph via @posthog/quill-charts, gated behind `product-analytics-quill-sql-charts`.
 * Grouped, stacked, and percent-stacked layouts; mixed series, trend lines, and right-axis series fall
 * back to legacy. Percent-stacked tooltips show fractions, not raw + % — the rich tooltip isn't bridged yet.
 */
export const SqlBarGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlBarGraph(props)

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
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
