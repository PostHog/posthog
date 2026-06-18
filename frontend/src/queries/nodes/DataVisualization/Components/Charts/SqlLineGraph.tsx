import clsx from 'clsx'
import { useCallback } from 'react'

import { ChartLegend, DefaultTooltip, TimeSeriesLineChart, type TooltipContext } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta, formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { useSqlLineGraph } from './useSqlLineGraph'

const handleChartError = makeChartErrorHandler('sql-line-chart')

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link LineGraph}). Handles line, area, and goal
 * lines; everything else falls back to the legacy chart.js path. The tooltip is quill's
 * DefaultTooltip extended to format each row with its column's own settings and to show a total row.
 */
export const SqlLineGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlLineGraph(props)
    const { chartSettings } = props
    const totalSettings = model?.totalFormatterSettings

    // config = behavior (pin/hover); render prop = content. Each row formats with its own column's
    // settings; the total uses the left-axis/first-series settings.
    const renderTooltip = useCallback(
        (ctx: TooltipContext<SqlLineSeriesMeta>): JSX.Element => (
            <DefaultTooltip<SqlLineSeriesMeta>
                {...ctx}
                valueFormatter={(value, entry) => formatSqlSeriesValue(value, entry.series.meta?.settings)}
                showTotal={chartSettings.showTotalRow !== false}
                totalFormatter={(value) => formatSqlSeriesValue(value, totalSettings)}
            />
        ),
        [chartSettings, totalSettings]
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
                    <TimeSeriesLineChart<SqlLineSeriesMeta>
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
