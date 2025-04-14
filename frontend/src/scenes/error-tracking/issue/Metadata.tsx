import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { useState } from 'react'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { match } from 'ts-pattern'

import { ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { Collapsible } from '../components/Collapsible'
import { SparklineChart, SparklineDatum, SparklineEvent } from '../components/SparklineChart/SparklineChart'
import { TimeBoundary } from '../components/TimeBoundary'
import { useSparklineDataIssueScene } from '../hooks/use-sparkline-data'
import { useSparklineEvents } from '../hooks/use-sparkline-events'
import { useSparklineOptions } from '../hooks/use-sparkline-options'
import { cancelEvent } from '../utils'

type SelectedDataType =
    | {
          type: 'datum'
          data: SparklineDatum
      }
    | {
          type: 'event'
          data: SparklineEvent<string>
      }
    | null

export const Metadata = (): JSX.Element => {
    const [isChartExpanded, setIsChartExpanded] = useState(true)
    const { aggregations, summaryLoading, issueLoading, firstSeen, lastSeen } = useValues(errorTrackingIssueSceneLogic)
    const [hoveredDatum, setHoveredDatum] = useState<SelectedDataType>(null)
    const sparklineData = useSparklineDataIssueScene()
    const sparklineEvents = useSparklineEvents()
    const sparklineOptions = useSparklineOptions(
        {
            onDatumMouseEnter: (d: SparklineDatum) => {
                setHoveredDatum({ type: 'datum', data: d })
            },
            onDatumMouseLeave: () => {
                setHoveredDatum(null)
            },
            onEventMouseEnter: (d: SparklineEvent<string>) => {
                setHoveredDatum({ type: 'event', data: d })
            },
            onEventMouseLeave: () => {
                setHoveredDatum(null)
            },
        },
        [setHoveredDatum]
    )

    return (
        <LemonCard className="p-1" hoverEffect={false} onClick={() => setIsChartExpanded(!isChartExpanded)}>
            <div className="flex justify-between items-center h-[30px] px-2">
                {match(hoveredDatum)
                    .when(
                        (data) => shouldRenderIssueMetrics(data),
                        () => <IssueMetrics aggregations={aggregations} summaryLoading={summaryLoading} />
                    )
                    .with({ type: 'datum' }, (data) => renderDataPoint(data.data))
                    .with({ type: 'event' }, (data) => renderEventPoint(data.data))
                    .otherwise(() => null)}
                <div className="flex justify-end items-center h-full">
                    {match(hoveredDatum)
                        .when(
                            (data) => shouldRenderIssueMetrics(data),
                            () => (
                                <>
                                    <TimeBoundary
                                        time={firstSeen}
                                        loading={issueLoading}
                                        label="First Seen"
                                        updateDateRange={(dateRange) => {
                                            dateRange.date_from = firstSeen?.toISOString()
                                            return dateRange
                                        }}
                                    />
                                    <IconChevronRight />
                                    <TimeBoundary
                                        time={lastSeen}
                                        loading={summaryLoading}
                                        label="Last Seen"
                                        updateDateRange={(dateRange) => {
                                            dateRange.date_to = lastSeen?.endOf('minute').toISOString()
                                            return dateRange
                                        }}
                                    />
                                </>
                            )
                        )
                        .with({ type: 'datum' }, (data) => renderDate(data.data.date))
                        .with({ type: 'event' }, (data) => renderDate(data.data.date))
                        .otherwise(() => null)}
                </div>
            </div>
            <Collapsible isExpanded={isChartExpanded} minHeight={0} className="p-0 overflow-hidden cursor-default">
                <div onClick={cancelEvent}>
                    <SparklineChart
                        data={sparklineData}
                        events={sparklineEvents}
                        options={sparklineOptions}
                        className="h-full pt-1"
                    />
                </div>
            </Collapsible>
        </LemonCard>
    )
}

function shouldRenderIssueMetrics(data: SelectedDataType): boolean {
    if (data == null) {
        return true
    }
    if (data.type == 'datum' && data.data.value == 0) {
        return true
    }
    return false
}

function IssueMetrics({
    aggregations,
    summaryLoading,
}: {
    aggregations: ErrorTrackingIssueAggregations | undefined
    summaryLoading: boolean
}): JSX.Element {
    const hasSessionCount = aggregations && aggregations.sessions !== 0
    return (
        <div className="flex items-center h-full gap-3 p-1">
            {renderMetric('Occurrences', aggregations?.occurrences, summaryLoading)}
            {renderMetric(
                'Sessions',
                aggregations?.sessions,
                summaryLoading,
                hasSessionCount ? undefined : 'No $session_id was set for any event in this issue'
            )}
            {renderMetric('Users', aggregations?.users, summaryLoading)}
        </div>
    )
}

function renderMetric(name: string, value: number | undefined, loading: boolean, tooltip?: string): JSX.Element {
    return (
        <>
            {match([loading])
                .with([true], () => <LemonSkeleton className="w-[80px] h-2" />)
                .with([false], () => (
                    <Tooltip title={tooltip} delayMs={0} placement="right">
                        <div className="flex items-center gap-1">
                            <div className="text-lg font-bold inline-block">
                                {value == null ? '0' : humanFriendlyLargeNumber(value)}
                            </div>
                            <div className="text-xs text-muted inline-block">{name}</div>
                        </div>
                    </Tooltip>
                ))
                .exhaustive()}
        </>
    )
}

function renderDate(date: Date): JSX.Element {
    return <div className="text-xs text-muted whitespace-nowrap">{dayjs(date).format('D MMM YYYY HH:mm (UTC)')}</div>
}

function renderDataPoint(d: SparklineDatum): JSX.Element {
    return (
        <div className="flex justify-start items-center h-full gap-1">
            <div className="text-lg font-bold">{humanFriendlyLargeNumber(d.value)}</div>
            <div className="text-xs text-muted">Occurrences</div>
        </div>
    )
}

function renderEventPoint(d: SparklineEvent<string>): JSX.Element {
    return (
        <div className="flex justify-start items-center h-full gap-1">
            <div className="text-lg font-bold">{d.payload}</div>
        </div>
    )
}
