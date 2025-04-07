import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { useState } from 'react'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { match } from 'ts-pattern'

import { ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { SparklineChart, SparklineDatum, SparklineEvent } from '../components/SparklineChart/SparklineChart'
import { DateRangeFilter } from '../ErrorTrackingFilters'
import { useSparklineDataIssueScene } from '../hooks/use-sparkline-data'
import { useSparklineEvents } from '../hooks/use-sparkline-events'
import { useSparklineOptions } from '../hooks/use-sparkline-options'

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
    const { aggregations, summaryLoading } = useValues(errorTrackingIssueSceneLogic)
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
        <LemonCard
            hoverEffect={false}
            className="grid grid-cols-[minmax(180px,min-content)_1fr] grid-rows-[50px_minmax(200px,_1fr)] p-0 overflow-hidden items-center"
        >
            <div className="border-r h-full flex items-center justify-center p-2 border-b">
                <DateRangeFilter fullWidth />
            </div>
            <div className="h-full p-1 row-span-2">
                <SparklineChart
                    data={sparklineData}
                    events={sparklineEvents}
                    options={sparklineOptions}
                    className="h-full"
                />
            </div>
            <div className="border-r h-full">
                {match(hoveredDatum)
                    .when(shouldRenderIssueMetrics, () => (
                        <IssueMetrics aggregations={aggregations} summaryLoading={summaryLoading} />
                    ))
                    .with({ type: 'datum' }, (s) => renderDataPoint(s.data))
                    .with({ type: 'event' }, (s) => renderEventPoint(s.data))
                    .otherwise(() => null)}
            </div>
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
        <div className="flex flex-col justify-around items-start h-full p-4">
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
        <div className="flex items-end gap-2">
            {match([loading])
                .with([true], () => <LemonSkeleton className="w-[80px] h-2" />)
                .with([false], () => (
                    <Tooltip title={tooltip} delayMs={0} placement="right">
                        <div className="text-2xl font-bold">
                            {value == null ? '0' : humanFriendlyLargeNumber(value)}
                        </div>
                        <div className="text-xs text-muted">{name}</div>
                    </Tooltip>
                ))
                .exhaustive()}
        </div>
    )
}

function renderDataPoint(d: SparklineDatum): JSX.Element {
    return (
        <div className="flex flex-col justify-between items-center h-full p-2">
            <div className="flex flex-col justify-center items-center  flex-grow">
                <div className="text-3xl font-bold">{humanFriendlyLargeNumber(d.value)}</div>
                <div className="text-xs text-muted">Occurrences</div>
            </div>
            <div className="text-xs text-muted">{dayjs(d.date).format('D MMM YYYY HH:mm (UTC)')}</div>
        </div>
    )
}

function renderEventPoint(d: SparklineEvent<string>): JSX.Element {
    return (
        <div className="flex flex-col justify-between items-center h-full p-2">
            <div className="flex flex-col justify-center items-center  flex-grow">
                <div className="text-2xl font-bold whitespace-nowrap">{dayjs(d.date).fromNow()}</div>
                <div className="text-xs text-muted">{d.payload}</div>
            </div>
            <div className="text-xs text-muted whitespace-nowrap">{dayjs(d.date).format('D MMM YYYY HH:mm (UTC)')}</div>
        </div>
    )
}
