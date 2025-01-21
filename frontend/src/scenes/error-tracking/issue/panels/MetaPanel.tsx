import { TZLabel } from '@posthog/apps-common'
import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

export const MetaPanel = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    const hasSessionCount = issue && issue.sessions != 0

    const Sessions = (
        <div className="flex flex-col flex-1">
            <div className="flex text-muted text-xs space-x-px">
                <span>Sessions</span>
                {!hasSessionCount && <IconInfo className="mt-0.5" />}
            </div>
            <div className="text-2xl font-semibold">
                {issue ? (hasSessionCount ? humanFriendlyLargeNumber(issue.sessions) : '-') : null}
            </div>
        </div>
    )

    return (
        <div className="space-y-4 p-2">
            {issue ? <div className="italic line-clamp-3">{issue.description}</div> : <LemonSkeleton />}
            <div className="flex space-x-2">
                <div className="flex-1">
                    <div className="text-muted text-xs">First seen</div>
                    {issue ? <TZLabel time={issue.first_seen} className="border-dotted border-b" /> : <LemonSkeleton />}
                </div>
                <div className="flex-1">
                    <div className="text-muted text-xs">Last seen</div>
                    {issue ? <TZLabel time={issue.last_seen} className="border-dotted border-b" /> : <LemonSkeleton />}
                </div>
            </div>
            <div className="flex space-x-2 justify-between gap-8">
                <div className="flex flex-col flex-1">
                    <div className="text-muted text-xs">Occurrences</div>
                    <div className="text-2xl font-semibold">
                        {issue?.occurrences ? humanFriendlyLargeNumber(issue.occurrences) : null}
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
                        {issue?.users ? humanFriendlyLargeNumber(issue.users) : null}
                    </div>
                </div>
            </div>
        </div>
    )
}
