import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { match } from 'ts-pattern'

import { OccurrenceSparkline, useSparklineData } from '../OccurrenceSparkline'

export const Metadata = (): JSX.Element => {
    const { summary, aggregations, volumeResolution, summaryLoading, dateRange } =
        useValues(errorTrackingIssueSceneLogic)
    const { values, labels } = useSparklineData(volumeResolution, dateRange, aggregations?.volumeRange)
    const hasSessionCount = summary && aggregations && aggregations.sessions !== 0
    return (
        <LemonCard hoverEffect={false} className="grid grid-cols-[min-content_1fr] p-0">
            <div className="flex flex-col justify-around items-start h-full p-4 border-r w-full min-w-[150px]">
                {renderMetric('Occurrences', aggregations?.occurrences, summaryLoading)}
                {renderMetric(
                    'Sessions',
                    aggregations?.sessions,
                    summaryLoading,
                    hasSessionCount ? undefined : 'No $session_id was set for any event in this issue'
                )}
                {renderMetric('Users', aggregations?.users, summaryLoading)}
            </div>
            <div className="flex flex-col gap-2 w-full p-4">
                <OccurrenceSparkline className="h-32 w-full" values={values} labels={labels} displayXAxis={true} />
            </div>
        </LemonCard>
    )
}

function renderMetric(name: string, value: number | undefined, loading: boolean, tooltip?: string): JSX.Element {
    return (
        <div className="flex items-end gap-2">
            {match([loading])
                .with([true], () => <LemonSkeleton className="w-[80px] h-2" />)
                .with([false], () => (
                    <Tooltip title={tooltip} delayMs={0} placement="bottom">
                        <div className="whitespace-nowrap">
                            <div className="text-2xl font-bold leading-7 inline-block mr-2">
                                {value == null ? '0' : humanFriendlyLargeNumber(value)}
                            </div>
                            <div className="text-muted text-xs leading-7 align-baseline inline-block">{name}</div>
                        </div>
                    </Tooltip>
                ))
                .exhaustive()}
        </div>
    )
}
