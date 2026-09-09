import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { MetricCard } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_LABELS,
    type MetricSummary,
    computeMetricChange,
    computeMetricSummary,
} from 'lib/components/Metric/metricSummary'
import { hexToRGBA } from 'lib/utils/colors'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { teamLogic } from 'scenes/teamLogic'

import { MetricChartSettings } from '~/queries/schema/schema-general'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { AxisSeries } from '../../dataVisualizationLogic'
import { buildSqlDateLabelFormatter, formatSqlSeriesValue } from './sqlLineGraphAdapter'

const handleChartError = makeChartErrorHandler('sql-metric-chart')

export const SQL_METRIC_SUMMARY_DEFAULT: MetricSummary = 'latest'

const makeChangeColor = (hex: string): { background: string; foreground: string } => ({
    background: hexToRGBA(hex, 0.1),
    foreground: hex,
})

export interface SqlMetricCardProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[]
    metricSettings?: MetricChartSettings
    presetChartHeight?: boolean
    className?: string
}

export const SqlMetricCard = ({
    xData,
    yData,
    metricSettings,
    presetChartHeight,
    className,
}: SqlMetricCardProps): JSX.Element => {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
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
        const formatLabel = xData ? buildSqlDateLabelFormatter(xData, timezone) : undefined

        return {
            data: visiblePoints.map((point) => point.value),
            labels:
                xData && xData.column.dataIndex !== -1
                    ? visiblePoints.map((point) => (formatLabel ? formatLabel(point.label) : point.label))
                    : undefined,
            latestValue: lastFiniteIndex === -1 ? undefined : sortedPoints[lastFiniteIndex].value,
        }
    }, [series, xData, timezone])

    const summary = metricSettings?.summary ?? SQL_METRIC_SUMMARY_DEFAULT
    const total = data.filter((value) => Number.isFinite(value)).reduce((sum, value) => sum + value, 0)
    const headlineValue = computeMetricSummary(summary, total, data)
    const change = computeMetricChange(data)
    const colorByDirection = metricSettings?.colorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT
    const increaseLineColor = metricSettings?.lineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR
    const decreaseLineColor = metricSettings?.lineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR
    const lineColor =
        colorByDirection && change != null
            ? change.value >= 0
                ? increaseLineColor
                : decreaseLineColor
            : series?.settings?.display?.color

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
                    value={headlineValue}
                    data={data}
                    labels={labels}
                    theme={theme}
                    color={lineColor}
                    change={change}
                    changeTooltip="Comparing the first point to the latest point."
                    showChange={metricSettings?.showChange ?? METRIC_SHOW_CHANGE_DEFAULT}
                    positiveColor={makeChangeColor(
                        metricSettings?.changeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR
                    )}
                    negativeColor={makeChangeColor(
                        metricSettings?.changeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR
                    )}
                    restingSubtitle={summary === 'latest' ? undefined : METRIC_SUMMARY_LABELS[summary]}
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
