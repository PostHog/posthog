import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import {
    AD_BLOCKED_CAPTURE_WINDOW_DAYS,
    adBlockedCaptureLogic,
} from 'lib/components/AdBlockedCapture/adBlockedCaptureLogic'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

export function AdBlockedCaptureRate(): JSX.Element {
    const { adBlockedCaptureStats, adBlockedCaptureStatsLoading, adBlockedCaptureShare, adBlockedCaptureFailed } =
        useValues(adBlockedCaptureLogic)
    const { loadAdBlockedCaptureStats } = useActions(adBlockedCaptureLogic)

    useEffect(() => {
        loadAdBlockedCaptureStats()
    }, [loadAdBlockedCaptureStats])

    if (adBlockedCaptureStatsLoading) {
        return <LemonSkeleton className="h-8 w-60" />
    }

    if (adBlockedCaptureFailed && !adBlockedCaptureStats) {
        return <p>The measurement did not load. Reload the page to try again.</p>
    }

    if (!adBlockedCaptureStats || adBlockedCaptureStats.totalSessions === 0 || adBlockedCaptureShare === null) {
        return (
            <p>
                There is nothing to measure yet. This needs sessions from the last {AD_BLOCKED_CAPTURE_WINDOW_DAYS}{' '}
                days.
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-2xl font-semibold" translate="no">
                    {percentage(adBlockedCaptureShare, 0)}
                </span>
                <span className="text-secondary">of sessions in the last {AD_BLOCKED_CAPTURE_WINDOW_DAYS} days</span>
            </div>
            <p>
                The recorder script did not load in{' '}
                <span translate="no">{humanFriendlyNumber(adBlockedCaptureStats.blockedSessions)}</span> of{' '}
                <span translate="no">{humanFriendlyNumber(adBlockedCaptureStats.totalSessions)}</span> sessions, so
                those sessions have no recording. An ad blocker is the usual cause.
            </p>
            {adBlockedCaptureStats.blockedSessions > 0 && (
                <p>
                    Route your data through your own domain with a{' '}
                    <Link to={urls.settings('organization-proxy')}>reverse proxy</Link> to record these sessions. The{' '}
                    <Link to="https://posthog.com/docs/session-replay/troubleshooting" target="_blank">
                        troubleshooting guide
                    </Link>{' '}
                    covers the other causes.
                </p>
            )}
        </div>
    )
}
