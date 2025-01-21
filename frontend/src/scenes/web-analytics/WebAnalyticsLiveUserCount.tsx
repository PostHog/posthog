import { IconLive } from '@posthog/icons'
import { useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
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
        <div className="flex flex-row items-center flex-1 justify-center sm:justify-start">
            <Tooltip title={tooltip}>
                <span className="whitespace-nowrap" data-attr="web-analytics-live-user-count">
                    <IconLive /> <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> currently online
                </span>
            </Tooltip>
        </div>
    )
}
