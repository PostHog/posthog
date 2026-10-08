import { useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { TrendsQuery } from '~/queries/schema/schema-general'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'
import {
    OBSERVATION_CHART_HEIGHT_CLASS,
    ReportObservationChart,
} from 'products/signals/frontend/inbox/components/detail/ReportObservationChart'
import {
    reportMetricAggregate,
    reportMetricChartType,
    reportMetricRowParts,
    reportMetricSeriesPoints,
    reportMetricWindowLabel,
} from 'products/signals/frontend/inbox/utils/reportMetrics'

/**
 * The report detail's live chart without its frame: what the metric measures and its live value on one
 * line, then the chart. The saved value shows until the live query answers.
 */
export function TodayReportHoverCardMetric({
    cardKey,
    metric,
    aggregateQuery,
    seriesQuery,
}: {
    cardKey: string
    metric: ReportMetricApi
    aggregateQuery: TrendsQuery
    seriesQuery: TrendsQuery
}): JSX.Element {
    const aggregateProps: DataNodeLogicProps = {
        key: `TodayReportMetricAggregate.${cardKey}.${metric.metric_id}`,
        query: aggregateQuery,
        autoLoad: true,
    }
    const seriesProps: DataNodeLogicProps = {
        key: `TodayReportMetricSeries.${cardKey}.${metric.metric_id}`,
        query: seriesQuery,
        autoLoad: true,
    }
    const { response } = useValues(dataNodeLogic(aggregateProps))
    const { response: seriesResponse, responseError: seriesError } = useValues(dataNodeLogic(seriesProps))

    const parts = reportMetricRowParts(metric, reportMetricAggregate(response) ?? metric.value)
    const points = reportMetricSeriesPoints(seriesResponse)
    const window = reportMetricWindowLabel(metric.query)
    const label = window ? `${metric.title}, ${window.toLowerCase()}` : metric.title

    return (
        <div className="flex flex-col gap-1.5" data-attr="today-report-hover-card-metric">
            <div className="flex items-baseline justify-between gap-2">
                <Text size="xs" variant="muted" render={<span title={label} />} className="truncate">
                    {label}
                </Text>
                {parts && (
                    <Text size="xs" render={<span translate="no" />} className="shrink-0 font-semibold tabular-nums">
                        {`${parts.value} ${parts.unit}`}
                    </Text>
                )}
            </div>
            {points ? (
                <ReportObservationChart
                    metric={metric}
                    points={points}
                    type={reportMetricChartType(metric)}
                    interval={seriesQuery.interval}
                />
            ) : !seriesError && seriesResponse == null ? (
                <Skeleton className={`${OBSERVATION_CHART_HEIGHT_CLASS} w-full`} />
            ) : null}
        </div>
    )
}
