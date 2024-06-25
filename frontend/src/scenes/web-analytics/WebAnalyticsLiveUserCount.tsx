import { IconLive } from '@posthog/icons'
import { useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { liveEventsTableLogic } from 'scenes/web-analytics/liveWebAnalyticsLogic'

export const WebAnalyticsLiveUserCount = (): JSX.Element | null => {
    const { liveUserCount, liveUserUpdatedSecondsAgo } = useValues(liveEventsTableLogic)
    const { currentTeam } = useValues(teamLogic)

    if (liveUserCount == null || liveUserUpdatedSecondsAgo == null) {
        return null
    }

    const inTeamString = currentTeam ? ` in ${currentTeam.name}` : ''
    const tooltip = `${humanFriendlyNumber(
        liveUserCount
    )} users are online${inTeamString} (updated ${liveUserUpdatedSecondsAgo} seconds ago)`

    return (
        <div className="flex-row">
            <Tooltip title={tooltip}>
                <span>
                    <IconLive /> <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> currently online
                </span>
            </Tooltip>
        </div>
    )
}
