import clsx from 'clsx'
import { useCallback } from 'react'

import { TimeSeriesBarChart, type PointClickData } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { LineGraphProps } from './LineGraph'
import { type SqlLineSeriesMeta, buildBarChartConfig } from './sqlLineGraphAdapter'
import { useSqlChartModel, useSqlDateRangeZoom } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-bar-chart')

export const SqlBarGraph = (props: LineGraphProps): JSX.Element => {
    const { onPointClick: onPointClickProp } = props
    const model = useSqlChartModel(props, buildBarChartConfig)
    const onDateRangeZoom = useSqlDateRangeZoom(props)

    const onPointClick = useCallback(
        (data: PointClickData<SqlLineSeriesMeta>) => {
            onPointClickProp?.(data.series.key, data.dataIndex, data.label)
        },
        [onPointClickProp]
    )

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
                    onPointClick={onPointClickProp ? onPointClick : undefined}
                    onDateRangeZoom={onDateRangeZoom}
                    onError={handleChartError}
                />
            )}
        </div>
    )
}
