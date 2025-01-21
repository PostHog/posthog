import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

export const MetaPanel = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

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
            <div className="flex space-x-2 justify-between mr-6">
                <div>
                    <div className="text-muted text-xs">Occurrences</div>
                    <div className="text-2xl font-semibold">
                        {issue?.occurrences ? humanFriendlyLargeNumber(issue.occurrences) : null}
                    </div>
                </div>
                <div>
                    <div className="text-muted text-xs">Sessions</div>
                    <div className="text-2xl font-semibold">
                        {issue?.sessions ? humanFriendlyLargeNumber(issue.sessions) : null}
                    </div>
                </div>
                <div>
                    <div className="text-muted text-xs">Users</div>
                    <div className="text-2xl font-semibold">
                        {issue?.users ? humanFriendlyLargeNumber(issue.users) : null}
                    </div>
                </div>
            </div>
        </div>
    )
}
