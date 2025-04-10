import './WebAnalyticsLiveUserCount.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
import { useEffect } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { liveWebAnalyticsLogic } from 'scenes/web-analytics/liveWebAnalyticsLogic'

const TooltipContent = (): JSX.Element | null => {
    const { currentTeam } = useValues(teamLogic)
    const { liveUserUpdatedSecondsAgo, liveUserCount } = useValues(liveWebAnalyticsLogic)
    const { setIsHovering } = useActions(liveWebAnalyticsLogic)

    // This is only rendered when the tooltip is open, so we will let the Kea interval knows
    // when we're rendered and when we're not
    useEffect(() => {
        setIsHovering(true)
        return () => setIsHovering(false)
    }, [setIsHovering])

    if (liveUserCount == null) {
        return null
    }

    const updatedAgoString =
        liveUserUpdatedSecondsAgo === 0
            ? ' (updated just now)'
            : liveUserUpdatedSecondsAgo == null
            ? ''
            : ` (updated ${liveUserUpdatedSecondsAgo} seconds ago)`

    const usersOnlineString = `${humanFriendlyNumber(liveUserCount)} ${
        liveUserCount === 1 ? 'user is' : 'users are'
    } online`
    const inTeamString = currentTeam ? ` in ${currentTeam.name}` : ''
    const tooltip = `${usersOnlineString}${inTeamString}${updatedAgoString}`
    return <>{tooltip}</>
}

export const WebAnalyticsLiveUserCount = (): JSX.Element | null => {
    const { liveUserCount } = useValues(liveWebAnalyticsLogic)

    // No data yet, or feature flag disabled
    if (liveUserCount == null) {
        return null
    }

    return (
        <Tooltip title={<TooltipContent />} interactive={true} delayMs={0}>
            <div className="flex flex-row items-center justify-center">
                <div className={clsx('live-user-indicator', liveUserCount > 0 ? 'online' : 'offline')} />
                <span className="whitespace-nowrap" data-attr="web-analytics-live-user-count">
                    <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> online
                </span>
            </div>
        </Tooltip>
    )
}
