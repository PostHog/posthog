import clsx from 'clsx'

import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { buildBarChartConfig } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-bar-chart')

export const SqlBarGraph = (props: LineGraphProps): JSX.Element => {
    const model = useSqlChartModel(props, buildBarChartConfig)

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
