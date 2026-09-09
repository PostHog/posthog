import clsx from 'clsx'
import { useMemo } from 'react'

import { MetricCard } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { AxisSeries } from '../../dataVisualizationLogic'
import { formatSqlSeriesValue } from './sqlLineGraphAdapter'

const handleChartError = makeChartErrorHandler('sql-metric-chart')

export interface SqlMetricCardProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[]
    presetChartHeight?: boolean
    className?: string
}

export const SqlMetricCard = ({ xData, yData, presetChartHeight, className }: SqlMetricCardProps): JSX.Element => {
    const theme = useChartTheme()
    const series = yData[0]
    const { data, labels, latestValue } = useMemo(() => {
        const points =
            series?.data.map((value, index) => ({
                value: value != null && Number.isFinite(value) ? value : NaN,
                label: xData?.data[index] ?? '',
            })) ?? []
        const isDateAxis = xData?.column.type.name === 'DATE' || xData?.column.type.name === 'DATETIME'
        const sortedPoints = isDateAxis ? points.sort((a, b) => Date.parse(a.label) - Date.parse(b.label)) : points
        const lastFiniteIndex = sortedPoints.findLastIndex((point) => Number.isFinite(point.value))
        const visiblePoints = sortedPoints.slice(0, lastFiniteIndex + 1)

        return {
            data: visiblePoints.map((point) => point.value),
            labels: xData && xData.column.dataIndex !== -1 ? visiblePoints.map((point) => point.label) : undefined,
            latestValue: lastFiniteIndex === -1 ? undefined : sortedPoints[lastFiniteIndex].value,
        }
    }, [series, xData])

    return (
        <div
            className={clsx(className, 'Metric ph-no-capture rounded bg-surface-primary flex flex-1 min-h-0 p-3', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            {series && latestValue !== undefined ? (
                <MetricCard
                    title={null}
                    value={latestValue}
                    data={data}
                    labels={labels}
                    theme={theme}
                    color={series.settings?.display?.color}
                    changeInline
                    hoverChangeFromPreviousPoint
                    sparklineFill
                    sparklineClassName="mt-4 -mx-3 -mb-3"
                    formatValue={(value) => formatSqlSeriesValue(value, series.settings)}
                    dataAttr="metric-value"
                    onError={handleChartError}
                />
            ) : (
                <InsightEmptyState sampleDataVariant="number" />
            )}
        </div>
    )
}
