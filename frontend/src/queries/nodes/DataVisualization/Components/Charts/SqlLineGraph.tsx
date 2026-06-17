import clsx from 'clsx'

import { ChartLegend, TimeSeriesLineChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { useSqlLineGraph } from './useSqlLineGraph'

const handleChartError = makeChartErrorHandler('sql-line-chart')

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the `data-viz-quill-charts`
 * flag (see {@link LineGraph}). Handles line, area, dual y-axis, and goal lines; everything else
 * falls back to the legacy chart.js path. Tooltip content is quill's DefaultTooltip until PR2 ports
 * the rich InsightTooltip.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element | null => {
    const model = useSqlLineGraph(props)
    if (!model) {
        return null
    }

    const { series, labels, theme, config, legendItems, hiddenKeys, toggleSeries } = model

    return (
        <div
            className={clsx(
                props.className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col',
                { 'h-[60vh]': props.presetChartHeight, 'h-full': !props.presetChartHeight }
            )}
        >
            <ChartLegend
                show={legendItems.length > 0}
                items={legendItems}
                hiddenKeys={hiddenKeys}
                onItemClick={toggleSeries}
                position="top"
            >
                <TimeSeriesLineChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={config}
                    onError={handleChartError}
                />
            </ChartLegend>
        </div>
    )
}
