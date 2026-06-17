import clsx from 'clsx'

import { Legend, TimeSeriesLineChart, type TooltipContext, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { formatDataWithSettings } from '../../dataVisualizationLogic'
import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta } from './sqlLineGraphAdapter'
import { useSqlLineGraph } from './useSqlLineGraph'

const handleChartError = makeChartErrorHandler('sql-line-chart')

// TODO(PR2): reuse the shared TrendsTooltip (TooltipContext -> InsightTooltip bridge) instead of
// this minimal placeholder, once the SQL meta carries the fields InsightTooltip needs.
function renderTooltip(ctx: TooltipContext<SqlLineSeriesMeta>): JSX.Element {
    return (
        <TooltipSurface>
            <div className="font-semibold mb-1">{ctx.label}</div>
            {ctx.seriesData.map((point) => (
                <div key={point.series.key} className="flex items-center gap-2">
                    <TooltipSwatch color={point.color} />
                    <span className="flex-1">{point.series.label}</span>
                    <span className="text-right">
                        {String(formatDataWithSettings(point.value, point.series.meta?.settings) ?? point.value)}
                    </span>
                </div>
            ))}
        </TooltipSurface>
    )
}

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the `data-viz-quill-charts`
 * flag (see {@link LineGraph}). Handles line, area, dual y-axis, and goal lines; everything else
 * falls back to the legacy chart.js path.
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
            {legendItems.length > 0 && (
                <Legend
                    items={legendItems}
                    hiddenKeys={hiddenKeys}
                    onItemClick={toggleSeries}
                    className="flex-none px-3 pt-2"
                />
            )}
            <div className="flex-1 min-h-0">
                <TimeSeriesLineChart<SqlLineSeriesMeta>
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={config}
                    tooltip={renderTooltip}
                    onError={handleChartError}
                />
            </div>
        </div>
    )
}
