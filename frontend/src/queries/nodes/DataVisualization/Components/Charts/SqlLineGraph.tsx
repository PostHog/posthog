import clsx from 'clsx'

import { ChartLegend, TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { useSqlLineGraph } from './useSqlLineGraph'

const handleChartError = makeChartErrorHandler('sql-line-chart')

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles line, area, and goal
 * lines; everything else falls back to the legacy chart.js path. Tooltip content is quill's
 * DefaultTooltip — the rich InsightTooltip isn't bridged over yet.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlLineGraph(props)

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
                    <TimeSeriesLineChart
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
