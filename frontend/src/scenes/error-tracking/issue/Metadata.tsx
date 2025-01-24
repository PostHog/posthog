import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

import { sparklineLabelsDay, sparklineLabelsMonth } from '../utils'

export const Metadata = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    const hasSessionCount = issue && issue.aggregations && issue.aggregations.sessions != 0

    const Count = ({ value }: { value: number | undefined }): JSX.Element => {
        return issue && issue.aggregations ? (
            <div className="text-2xl font-semibold">{value ? humanFriendlyLargeNumber(value) : '-'}</div>
        ) : (
            <div className="flex flex-1 items-center">
                <LemonSkeleton />
            </div>
        )
    }

    const Sessions = (
        <div className="flex flex-col flex-1">
            <div className="flex text-muted text-xs space-x-px">
                <span>Sessions</span>
                {!hasSessionCount && <IconInfo className="mt-0.5" />}
            </div>
            <Count value={issue?.aggregations?.sessions} />
        </div>
    )

    return (
        <div className="space-y-4 p-2">
            {issue ? <div className="italic line-clamp-3">{issue.description}</div> : <LemonSkeleton />}
            <div className="flex space-x-2">
                <div className="flex-1">
                    <div className="text-muted text-xs">First seen</div>
                    {issue ? <TZLabel time={issue.firstSeen} className="border-dotted border-b" /> : <LemonSkeleton />}
                </div>
                <div className="flex-1">
                    <div className="text-muted text-xs">Last seen</div>
                    {issue && issue.lastSeen ? (
                        <TZLabel time={issue.lastSeen} className="border-dotted border-b" />
                    ) : (
                        <LemonSkeleton />
                    )}
                </div>
            </div>
            <div className="flex space-x-2 justify-between gap-8">
                <div className="flex flex-col flex-1">
                    <div className="text-muted text-xs">Occurrences</div>
                    <div className="text-2xl font-semibold">
                        <Count value={issue?.aggregations?.occurrences} />
                    </div>
                </div>
                {hasSessionCount ? (
                    Sessions
                ) : (
                    <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
                        {Sessions}
                    </Tooltip>
                )}
                <div className="flex flex-col flex-1">
                    <div className="text-muted text-xs">Users</div>
                    <div className="text-2xl font-semibold">
                        <Count value={issue?.aggregations?.users} />
                    </div>
                </div>
            </div>
            <div className="space-y-1">
                <div className="text-muted text-xs">Last 24 hours</div>
                <div>
                    <Sparkline
                        loading={!issue?.aggregations?.volumeDay}
                        className="h-12"
                        data={issue?.aggregations?.volumeDay || Array(24).fill(0)}
                        labels={sparklineLabelsDay}
                    />
                </div>
            </div>
            <div className="space-y-1">
                <div className="text-muted text-xs">Last month</div>
                <div>
                    <Sparkline
                        loading={!issue?.aggregations?.volumeMonth}
                        className="h-12"
                        data={issue?.aggregations?.volumeMonth || Array(31).fill(0)}
                        labels={sparklineLabelsMonth}
                    />
                </div>
            </div>
        </div>
    )
}
