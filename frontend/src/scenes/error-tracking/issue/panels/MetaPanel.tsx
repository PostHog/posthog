import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber, isString } from 'lib/utils'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

export const MetaPanel = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    const sessions = issue?.aggregations?.sessions

    return (
        <div className="space-y-4 p-2">
            {issue ? <div className="italic line-clamp-3">{issue.description}</div> : <LemonSkeleton />}
            <div className="flex space-x-2">
                <div className="flex-1">
                    <div className="text-secondary text-xs">First seen</div>
                    {issue ? <TZLabel time={issue.first_seen} className="border-dotted border-b" /> : <LemonSkeleton />}
                </div>
                <div className="flex-1">
                    <div className="text-secondary text-xs">Last seen</div>
                    {issue?.last_seen ? (
                        <TZLabel time={issue.last_seen} className="border-dotted border-b" />
                    ) : (
                        <LemonSkeleton />
                    )}
                </div>
            </div>
            <div className="flex space-x-2 justify-between gap-8">
                <Count label="Occurrences" value={issue?.aggregations?.occurrences} />
                <Count
                    tooltip="No $session_id was set for any event in this issue"
                    label="Sessions"
                    value={sessions && sessions > 0 ? sessions : '-'}
                />
                <Count label="Users" value={issue?.aggregations?.users} />
            </div>
        </div>
    )
}

const Count = ({
    label,
    value,
    tooltip,
}: {
    label: string
    value?: number | string
    tooltip?: string
}): JSX.Element => {
    const Component = (
        <div className="flex flex-col flex-1">
            <div className="flex text-secondary text-xs space-x-px">
                <span>{label}</span>
                {tooltip && <IconInfo className="mt-0.5" />}
            </div>
            <div className="text-2xl font-semibold">
                {value ? isString(value) ? value : humanFriendlyLargeNumber(value) : <LemonSkeleton />}
            </div>
        </div>
    )

    return tooltip ? (
        Component
    ) : (
        <Tooltip title={tooltip} delayMs={0}>
            {Component}
        </Tooltip>
    )
}
