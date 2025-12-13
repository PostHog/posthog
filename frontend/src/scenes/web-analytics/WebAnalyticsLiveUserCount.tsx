import './WebAnalyticsLiveUserCount.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
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

    const usersOnlineString = `${humanFriendlyNumber(liveUserCount)} ${
        liveUserCount === 1 ? 'user has' : 'users have'
    } been seen recently`
    const inTeamString = currentTeam ? ` in ${currentTeam.name}` : ''
    const updatedString =
        liveUserUpdatedSecondsAgo === 0
            ? 'updated just now'
            : liveUserUpdatedSecondsAgo == null
              ? ''
              : `updated ${liveUserUpdatedSecondsAgo} seconds ago`

    return (
        <div>
            <div>
                {usersOnlineString}
                {inTeamString}
            </div>
            {updatedString && <div className="text-xs">({updatedString})</div>}
        </div>
    )
}

export const WebAnalyticsLiveUserCount = (): JSX.Element | null => {
    const { liveUserCount } = useValues(liveWebAnalyticsLogic)

    // No data yet, or feature flag disabled
    if (liveUserCount == null) {
        return null
    }

    const isOnline = liveUserCount > 0

    return (
        <Tooltip
            title={<TooltipContent />}
            interactive={true}
            delayMs={0}
            docLink="https://posthog.com/docs/web-analytics/faq#i-am-online-but-the-online-user-count-is-not-reflecting-my-user"
        >
            <div
                className={clsx(
                    'flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors',
                    isOnline ? 'bg-success-highlight' : 'bg-border-light'
                )}
            >
                <div className={clsx('live-user-indicator', isOnline ? 'online' : 'offline')} />
                <span className="text-xs font-medium whitespace-nowrap" data-attr="web-analytics-live-user-count">
                    <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> recently online
                </span>
            </div>
        </Tooltip>
    )
}
