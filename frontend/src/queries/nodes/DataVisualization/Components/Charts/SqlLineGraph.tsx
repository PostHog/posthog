import clsx from 'clsx'

import { ChartLegend, TimeSeriesLineChart, type TooltipContext } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { type SqlLineSeriesMeta } from './sqlLineGraphAdapter'
import { SqlLineGraphTooltip } from './SqlLineGraphTooltip'
import { useSqlLineGraph } from './useSqlLineGraph'

const handleChartError = makeChartErrorHandler('sql-line-chart')

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles line, area, and goal
 * lines; everything else falls back to the legacy chart.js path. The rich {@link SqlLineGraphTooltip}
 * (ported from the legacy path) is supplied via quill's `tooltip` render prop, while pin/hover
 * behavior stays on the `TooltipConfig` in `buildLineChartConfig`.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlLineGraph(props)

    const renderTooltip = (context: TooltipContext<SqlLineSeriesMeta>): JSX.Element => (
        <SqlLineGraphTooltip context={context} chartSettings={props.chartSettings} />
    )

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
                        tooltip={renderTooltip}
                        onError={handleChartError}
                    />
                </ChartLegend>
            )}
        </div>
    )
}
