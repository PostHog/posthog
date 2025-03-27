import './WebAnalyticsLiveUserCount.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { liveEventsTableLogic } from 'scenes/web-analytics/liveWebAnalyticsLogic'

export const WebAnalyticsLiveUserCount = (): JSX.Element | null => {
    const { liveUserCount, liveUserUpdatedSecondsAgo } = useValues(liveEventsTableLogic)
    const { setNow } = useActions(liveEventsTableLogic)
    const { currentTeam } = useValues(teamLogic)
    const [isHovering, setIsHovering] = useState(false)
    const intervalRef = useRef<number | null>(null)

    // Start/stop the interval when tooltip visibility changes
    useEffect(() => {
        if (isHovering) {
            if (intervalRef.current !== null) {
                window.clearInterval(intervalRef.current)
            }

            intervalRef.current = window.setInterval(() => {
                setNow({ now: new Date() })
            }, 500)
        } else {
            if (intervalRef.current !== null) {
                window.clearInterval(intervalRef.current)
                intervalRef.current = null
            }
        }

        // Cleanup on component unmount
        return () => {
            if (intervalRef.current !== null) {
                window.clearInterval(intervalRef.current)
                intervalRef.current = null
            }
        }
    }, [isHovering, setNow])

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
            <div
                className="flex flex-row items-center justify-center"
                onMouseEnter={() => setIsHovering(true)}
                onMouseLeave={() => setIsHovering(false)}
            >
                <div className={clsx('live-user-indicator', liveUserCount > 0 ? 'online' : 'offline')} />
                <span className="whitespace-nowrap" data-attr="web-analytics-live-user-count">
                    <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong> online
                </span>
            </div>
        </Tooltip>
    )
}
