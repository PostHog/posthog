import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { ClampedText } from 'lib/lemon-ui/ClampedText'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

export const Metadata = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    const hasSessionCount = issue && issue.aggregations && issue.aggregations.sessions !== 0

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
            <div className="flex text-muted text-xs deprecated-space-x-px">
                <span>Sessions</span>
                {!hasSessionCount && <IconInfo className="mt-0.5" />}
            </div>
            <Count value={issue?.aggregations?.sessions} />
        </div>
    )

    return (
        <div className="deprecated-space-y-1">
            {issue && issue.description ? <ClampedText text={issue.description} lines={2} /> : <LemonSkeleton />}
            <div className="flex flex-1 justify-between">
                <div className="flex items-end deprecated-space-x-6">
                    <div>
                        <div className="text-muted text-xs">First seen</div>
                        {issue ? (
                            <TZLabel time={issue.first_seen} className="border-dotted border-b" />
                        ) : (
                            <LemonSkeleton />
                        )}
                    </div>
                    <div>
                        <div className="text-muted text-xs">Last seen</div>
                        {issue && issue.last_seen ? (
                            <TZLabel time={issue.last_seen} className="border-dotted border-b" />
                        ) : (
                            <LemonSkeleton />
                        )}
                    </div>
                </div>
                <div className="flex deprecated-space-x-2 gap-8 items-end">
                    <div className="flex flex-col flex-1">
                        <div className="text-muted text-xs">Occurrences</div>
                        <Count value={issue?.aggregations?.occurrences} />
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
                        <Count value={issue?.aggregations?.users} />
                    </div>
                </div>
            </div>
        </div>
    )
}
