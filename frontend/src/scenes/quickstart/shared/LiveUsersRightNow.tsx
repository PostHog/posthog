import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { liveUserCountLogic } from 'lib/components/LiveUserCount'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { captureQuickstartAction } from './captureQuickstartAction'

const QUICKSTART_LIVE_USERS_POLL_INTERVAL_MS = 1000

export function LiveUsersRightNow(): JSX.Element {
    const logicProps = { pollIntervalMs: QUICKSTART_LIVE_USERS_POLL_INTERVAL_MS }
    const { liveUserCount } = useValues(liveUserCountLogic(logicProps))
    const { pauseStream, resumeStream } = useActions(liveUserCountLogic(logicProps))
    const { isVisible } = usePageVisibility()
    const hasLiveUsers = (liveUserCount ?? 0) > 0

    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    return (
        <Link
            to={urls.webAnalyticsLive()}
            onClick={() => captureQuickstartAction('view_live_users')}
            className="flex items-center gap-1.5 text-xs text-tertiary hover:text-primary"
            data-attr="quickstart-live-users"
        >
            <span className="relative flex items-center justify-center shrink-0">
                {hasLiveUsers && (
                    <span className="absolute size-2.5 bg-success rounded-full animate-pulse opacity-30" />
                )}
                <span className={`relative size-1.5 rounded-full ${hasLiveUsers ? 'bg-success' : 'bg-muted-alt'}`} />
            </span>
            {liveUserCount === null ? (
                <span>View live users</span>
            ) : (
                <span>
                    <strong className="font-semibold text-primary">{humanFriendlyLargeNumber(liveUserCount)}</strong>{' '}
                    live {liveUserCount === 1 ? 'user' : 'users'}
                </span>
            )}
        </Link>
    )
}
