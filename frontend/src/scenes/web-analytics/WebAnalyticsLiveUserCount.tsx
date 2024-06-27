import { IconLive } from '@posthog/icons'
import { useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { liveEventsTableLogic } from 'scenes/web-analytics/liveWebAnalyticsLogic'

export const WebAnalyticsLiveUserCount = (): JSX.Element | null => {
    const { liveUserCount, liveUserUpdatedSecondsAgo } = useValues(liveEventsTableLogic)
    const { currentTeam } = useValues(teamLogic)

    if (liveUserCount == null) {
        // No data yet, or feature flag disabled
        return null
    }

    const usersOnlineString = `${humanFriendlyNumber(liveUserCount)} ${
        liveUserCount === 1 ? 'user is' : 'users are'
    } online`
    const inTeamString = currentTeam ? ` in ${currentTeam.name}` : ''
    const updatedAgoString =
        liveUserUpdatedSecondsAgo === 0
            ? ' (updated just now)'
            : liveUserUpdatedSecondsAgo == null
            ? ''
            : ` (updated ${liveUserUpdatedSecondsAgo} seconds ago)`
    const tooltip = `${usersOnlineString}${inTeamString}${updatedAgoString}`

    return (
        <div className="flex-row">
            <Tooltip title={tooltip}>
                <span>
                    <IconLive /> <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> currently online
                </span>
            </Tooltip>
            <div className="bg-border h-px w-full mt-2" />
        </div>
    )
}
