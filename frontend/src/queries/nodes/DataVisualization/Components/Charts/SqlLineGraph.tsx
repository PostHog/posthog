import clsx from 'clsx'

import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { useSqlLineGraph } from './useSqlLineGraph'

const handleChartError = makeChartErrorHandler('sql-chart')

/**
 * SQL line/area/bar graph via @posthog/quill-charts, gated behind `product-analytics-quill-sql-charts`.
 * Handles line, area, bar, stacked, and percent-stacked layouts plus goal lines; mixed series, trend
 * lines, and right-axis series fall back to legacy. Tooltips use quill's DefaultTooltip — the rich
 * InsightTooltip isn't bridged yet, so percent-stacked shows fractions, not raw + %.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlLineGraph(props)

    return (
        <div
            className={clsx(
                props.className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col',
                { 'h-[60vh]': props.presetChartHeight, 'h-full': !props.presetChartHeight }
            )}
        >
            {model &&
                (model.chartType === 'bar' ? (
                    <TimeSeriesBarChart
                        series={model.series}
                        labels={model.labels}
                        theme={model.theme}
                        config={model.config}
                        onError={handleChartError}
                    />
                ) : (
                    <TimeSeriesLineChart
                        series={model.series}
                        labels={model.labels}
                        theme={model.theme}
                        config={model.config}
                        onError={handleChartError}
                    />
                ))}
        </div>
    )
}
