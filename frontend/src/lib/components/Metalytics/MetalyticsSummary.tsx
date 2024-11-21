import { IconEye, IconPlay } from '@posthog/icons'
import { LemonButton, ProfileBubbles } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { metalyticsLogic } from './metalyticsLogic'
import { IconPulse, IconDashboard } from '@posthog/icons'
import { IconWithCount } from 'lib/lemon-ui/icons'

export function MetalyticsSummary(): JSX.Element | null {
    const { instanceId, viewCount, viewCountLoading, recentUserMembers } = useValues(metalyticsLogic)

    if (!instanceId) {
        return null
    }

    return (
        <>
            <ProfileBubbles tooltip="Recently Viewed By" people={recentUserMembers.map((x) => x.user)} limit={3} />
            <IconPulse className="mr-2"/>
            <IconWithCount count={7}>
                <IconDashboard />
            </IconWithCount>
            <LemonButton loading={viewCountLoading} type="secondary" icon={<IconEye />} size="small">
                {viewCount === null ? 'Loading...' : `Viewed ${viewCount} times`}
            </LemonButton>
        </>
    )
}
