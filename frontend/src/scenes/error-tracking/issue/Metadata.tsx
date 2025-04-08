import { IconInfo } from '@posthog/icons'
import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

import { OccurrenceSparkline, useSparklineData } from '../OccurrenceSparkline'

export const Metadata = (): JSX.Element => {
    const { summary, aggregations, summaryLoading, dateRange } = useValues(errorTrackingIssueSceneLogic)
    const { values, labels } = useSparklineData('custom', dateRange, aggregations)
    const hasSessionCount = summary && aggregations && aggregations.sessions !== 0

    return (
        <LemonCard hoverEffect={false} className="grid grid-cols-[min-content_1fr] p-0">
            <div className="flex flex-col justify-around items-start h-full px-6 py-3 border-r w-full">
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
                <OccurrenceSparkline
                    className="h-32 w-full"
                    values={values}
                    labels={labels}
                    displayXAxis={true}
                    loading={summaryLoading}
                />
            </div>
        </LemonCard>
    )
}

function renderMetric(name: string, value: number | undefined, loading: boolean, tooltip?: string): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            {loading ? (
                <LemonSkeleton />
            ) : (
                <Tooltip title={tooltip} delayMs={0} placement="bottom">
                    <div className="text-xl font-semibold">{value ? humanFriendlyLargeNumber(value) : '-'}</div>
                </Tooltip>
            )}
            <div className="flex items-center text-muted text-xs gap-1">
                {name}
                {!loading && tooltip && <IconInfo className="mt-0.5" />}
            </div>
        </div>
    )
}
