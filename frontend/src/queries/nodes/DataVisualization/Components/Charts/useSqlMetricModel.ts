import { useValues } from 'kea'
import { useMemo } from 'react'

import { type MetricChange } from '@posthog/quill-charts'

import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    type MetricSummary,
    computeMetricChange,
    computeMetricSummary,
    resolveMetricLineColor,
} from 'lib/components/Metric/metricSummary'
import { teamLogic } from 'scenes/teamLogic'

import { MetricChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries } from '../../dataVisualizationLogic'
import { buildSqlDateLabelFormatter } from './sqlLineGraphAdapter'

export const SQL_METRIC_SUMMARY_DEFAULT: MetricSummary = 'latest'

export interface SqlMetricModelArgs {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[]
    metricSettings?: MetricChartSettings
}

export interface SqlMetricModel {
    series: AxisSeries<number | null>
    summary: MetricSummary
    data: number[]
    labels: string[] | undefined
    headlineValue: number
    change: MetricChange | null | undefined
    lineColor: string | undefined
}

interface SqlMetricPoints {
    data: number[]
    labels: string[] | undefined
    latestValue: number | undefined
}

function buildSqlMetricPoints(
    series: AxisSeries<number | null> | undefined,
    xData: AxisSeries<string> | null,
    timezone: string
): SqlMetricPoints {
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
}

/** Returns null when there is no series or no finite value to show. */
export function useSqlMetricModel({ xData, yData, metricSettings }: SqlMetricModelArgs): SqlMetricModel | null {
    const { timezone } = useValues(teamLogic)
    const series = yData[0]
    const points = useMemo(() => buildSqlMetricPoints(series, xData, timezone), [series, xData, timezone])

    return useMemo(() => {
        if (!series || points.latestValue === undefined) {
            return null
        }
        const { data, labels } = points
        const summary = metricSettings?.summary ?? SQL_METRIC_SUMMARY_DEFAULT
        const total = data.filter((value) => Number.isFinite(value)).reduce((sum, value) => sum + value, 0)
        const change = computeMetricChange(data)

        return {
            series,
            summary,
            data,
            labels,
            headlineValue: computeMetricSummary(summary, total, data),
            change,
            lineColor: resolveMetricLineColor({
                colorByDirection: metricSettings?.colorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT,
                change,
                increaseColor: metricSettings?.lineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR,
                decreaseColor: metricSettings?.lineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR,
                fallback: series.settings?.display?.color,
            }),
        }
    }, [series, points, metricSettings])
}
