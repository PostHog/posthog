import clsx from 'clsx'

import { ChartLegend, TimeSeriesBarChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { useSqlBarGraph } from './useSqlBarGraph'

const handleChartError = makeChartErrorHandler('sql-bar-chart')

/**
 * SQL bar / stacked-bar graph rendered via @posthog/quill-charts, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles grouped, stacked, and
 * percent-stacked bars (incl. goal lines); mixed bar/line series, trend lines, and right-axis
 * series fall back to the legacy chart.js path. Tooltip content is quill's DefaultTooltip — the rich
 * InsightTooltip isn't bridged over yet, so percent-stacked tooltips show fractions, not raw + %.
 */
export const SqlBarGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlBarGraph(props)

    // Keep the styled container even with no data, matching the legacy path's background shell.
    return (
        <div
            className={clsx(
                props.className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col',
                { 'h-[60vh]': props.presetChartHeight, 'h-full': !props.presetChartHeight }
            )}
        >
            {model && (
                <ChartLegend
                    show={model.legendItems.length > 0}
                    items={model.legendItems}
                    hiddenKeys={model.hiddenKeys}
                    onItemClick={model.toggleSeries}
                    position="top"
                >
                    <TimeSeriesBarChart
                        series={model.series}
                        labels={model.labels}
                        theme={model.theme}
                        config={model.config}
                        onError={handleChartError}
                    />
                </ChartLegend>
            )}
        </div>
    )
}
