import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs } from 'lib/dayjs'
import { ClampedText } from 'lib/lemon-ui/ClampedText'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

import { OccurrenceSparkline, useSparklineData } from '../OccurrenceSparkline'

export const Metadata = (): JSX.Element => {
    const { firstSeen, summary, aggregations, lastSeen, summaryLoading, issue, issueLoading, issueDateRange } =
        useValues(errorTrackingIssueSceneLogic)
    const { values, labels } = useSparklineData('custom', issueDateRange, aggregations)
    const hasSessionCount = summary && aggregations && aggregations.sessions !== 0

    return (
        <div className="space-y-2 pb-5">
            {!issueLoading ? (
                <ClampedText text={issue?.description || ''} lines={2} />
            ) : (
                <LemonSkeleton.Row repeat={1} />
            )}
            <div className="flex flex-1 justify-between py-3">
                <div className="flex items-end space-x-6">
                    {renderTime('First seen', firstSeen, issueLoading)}
                    {renderTime('Last seen', lastSeen, summaryLoading)}
                </div>
                <div className="flex space-x-2 gap-8 items-end">
                    {renderMetric('Occurrences', aggregations?.occurrences, summaryLoading)}
                    {renderMetric(
                        'Sessions',
                        aggregations?.sessions,
                        summaryLoading,
                        hasSessionCount ? undefined : 'No $session_id was set for any event in this issue'
                    )}
                    {renderMetric('Users', aggregations?.users, summaryLoading)}
                </div>
            </div>
            <OccurrenceSparkline
                className="h-32 w-full"
                values={values}
                labels={labels}
                displayXAxis={true}
                loading={summaryLoading}
            />
        </div>
    )
}

function renderMetric(name: string, value: number | undefined, loading: boolean, tooltip?: string): JSX.Element {
    return (
        <div className="flex flex-col flex-1">
            <div className="flex items-center text-muted text-xs gap-1">
                {name}
                {!loading && tooltip && <IconInfo className="mt-0.5" />}
            </div>
            {loading ? (
                <LemonSkeleton />
            ) : (
                <Tooltip title={tooltip} delayMs={0} placement="bottom">
                    <div className="text-2xl font-semibold">{value ? humanFriendlyLargeNumber(value) : '-'}</div>
                </Tooltip>
            )}
        </div>
    )
}

function renderTime(label: string, time: Dayjs | null | undefined, loading: boolean): JSX.Element {
    return (
        <div>
            <div className="text-muted text-xs">{label}</div>
            {loading && <LemonSkeleton />}
            {!loading && time && <TZLabel time={time} className="border-dotted border-b" />}
            {!loading && !time && <>-</>}
        </div>
    )
}
