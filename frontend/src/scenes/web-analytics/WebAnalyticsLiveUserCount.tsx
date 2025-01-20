import { IconLive } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { liveEventsTableLogic } from 'scenes/web-analytics/liveWebAnalyticsLogic'

export const WebAnalyticsLiveUserCount = (): JSX.Element | null => {
    const { liveUserCount, liveUserUpdatedSecondsAgo } = useValues(liveEventsTableLogic)
    const { currentTeam } = useValues(teamLogic)

    // No data yet, or feature flag disabled
    if (liveUserCount == null) {
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
        <Tooltip title={tooltip}>
            <span>
                <IconLive /> <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> currently online
            </span>
        </Tooltip>
    )
}
