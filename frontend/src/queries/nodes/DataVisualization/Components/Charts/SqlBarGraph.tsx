import clsx from 'clsx'
import { useCallback, useMemo } from 'react'

import {
    BarChart,
    ReferenceLines,
    TimeSeriesBarChart,
    ValueLabels,
    type PointClickData,
    type ValueLabelContext,
} from '@posthog/quill-charts'

import { AnnotationsLayer } from 'lib/components/AnnotationsOverlay/AnnotationsLayer'

import { ChartDisplayType } from '~/types'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'
import { goalLinesToReferenceLines } from 'products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter'

import { type SqlChartProps } from './SqlChart'
import {
    type SqlBarGraphConfig,
    type SqlLineSeriesMeta,
    buildBarChartConfig,
    buildBarValueChartConfig,
    formatSqlSeriesValue,
} from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-bar-chart')

export const SqlBarGraph = (props: SqlChartProps): JSX.Element => {
    const { onPointClick: onPointClickProp } = props
    const isHorizontal = props.visualizationType === ChartDisplayType.ActionsBarValue
    const model = useSqlChartModel<SqlBarGraphConfig>(
        props,
        isHorizontal ? buildBarValueChartConfig : buildBarChartConfig
    )

    const onPointClick = useCallback(
        (data: PointClickData<SqlLineSeriesMeta>) => {
            onPointClickProp?.(data.series.key, data.dataIndex, String(props.xData?.data[data.dataIndex] ?? data.label))
        },
        [onPointClickProp, props.xData]
    )

    const series = model?.series
    const referenceLines = useMemo(
        () => (series && isHorizontal ? goalLinesToReferenceLines(props.goalLines, series, 'horizontal') : []),
        [isHorizontal, series, props.goalLines]
    )

    const valueLabelFormatter = useCallback(
        (_value: number, seriesIndex: number, _dataIndex: number, context: ValueLabelContext): string =>
            formatSqlSeriesValue(context.rawValue, series?.[seriesIndex]?.meta?.settings),
        [series]
    )

    return (
        <div
            className={clsx(props.className, 'rounded bg-surface-primary w-full grow relative flex flex-col', {
                'h-[60vh]': props.presetChartHeight,
                'h-full': !props.presetChartHeight,
                'overflow-y-auto': isHorizontal && !props.embedded,
                'overflow-hidden': !isHorizontal || props.embedded,
            })}
        >
            {model &&
                (isHorizontal ? (
                    <BarChart
                        series={model.series}
                        labels={model.labels}
                        theme={model.theme}
                        config={model.config}
                        onPointClick={onPointClickProp ? onPointClick : undefined}
                        onError={handleChartError}
                    >
                        <ReferenceLines lines={referenceLines} />
                        {props.chartSettings.showValuesOnSeries && <ValueLabels valueFormatter={valueLabelFormatter} />}
                    </BarChart>
                ) : (
                    <TimeSeriesBarChart
                        series={model.series}
                        labels={model.labels}
                        theme={model.theme}
                        config={model.config}
                        onPointClick={onPointClickProp ? onPointClick : undefined}
                        onError={handleChartError}
                    >
                        {props.showAnnotations && props.insightNumericId && (
                            <AnnotationsLayer insightNumericId={props.insightNumericId} dates={model.labels} />
                        )}
                    </TimeSeriesBarChart>
                ))}
        </div>
    )
}
