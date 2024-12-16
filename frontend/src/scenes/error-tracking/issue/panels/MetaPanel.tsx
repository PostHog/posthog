import { TZLabel } from '@posthog/apps-common'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

export const MetaPanel = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    return (
        <div className="space-y-2">
            {issue ? <div>{issue.description}</div> : <LemonSkeleton />}
            <div className="flex space-x-2">
                <div className="flex-1">
                    <div>First seen</div>
                    {issue ? <TZLabel time={issue.first_seen} className="border-dotted border-b" /> : <LemonSkeleton />}
                </div>
                <div className="flex-1">
                    <div>Last seen</div>
                    {issue ? <TZLabel time={issue.last_seen} className="border-dotted border-b" /> : <LemonSkeleton />}
                </div>
            </div>
            <div className="flex space-x-2">
                <div className="flex-1">
                    <div>Occurrences</div>
                    <div className="text-2xl font-semibold">{issue?.occurrences}</div>
                </div>
                <div className="flex-1">
                    <div>Sessions</div>
                    <div className="text-2xl font-semibold">{issue?.sessions}</div>
                </div>
                <div className="flex-1">
                    <div>Users</div>
                    <div className="text-2xl font-semibold">{issue?.users}</div>
                </div>
            </div>
            {/* {issue && <Sparkline data={issue.volume[5]} />} */}
        </div>
    )
}
