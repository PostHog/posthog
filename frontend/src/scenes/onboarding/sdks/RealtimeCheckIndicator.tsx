import { useEffect, useRef } from 'react'

import { IconCheck, IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { type AdblockDetectionResult } from './hooks/useAdblockDetection'
import { useInstallationComplete } from './hooks/useInstallationComplete'
import { OnboardingLiveEvents } from './OnboardingLiveEvents'

export type RealtimeCheckIndicatorProps = {
    teamPropertyToVerify: string
    listeningForName?: string
    /** Compact presentation for tight headers: no "Verify installation" label, no chip border. */
    minimal?: boolean
    /** Fires once when verification flips from waiting to complete. Already-complete mounts don't fire. */
    onComplete?: () => void
}

export function RealtimeCheckIndicator({
    teamPropertyToVerify,
    listeningForName = 'event',
    minimal = false,
    onComplete,
}: RealtimeCheckIndicatorProps): JSX.Element {
    const installationComplete = useInstallationComplete(teamPropertyToVerify)
    const wasComplete = useRef(installationComplete)
    useEffect(() => {
        if (installationComplete && !wasComplete.current) {
            onComplete?.()
        }
        wasComplete.current = installationComplete
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [installationComplete])

    return (
        <div className="flex items-center gap-3 min-w-0">
            {installationComplete ? (
                <div className="flex flex-row items-center gap-2 min-w-0">
                    <div className="flex items-center gap-2 px-2 py-1 font-medium shrink-0">
                        <IconCheck className="text-success" />
                        <span className="text-success text-sm whitespace-nowrap">Installation complete</span>
                    </div>
                    <OnboardingLiveEvents />
                </div>
            ) : (
                <div className="flex flex-row gap-3 items-center">
                    {!minimal && <div className="font-medium">Verify installation</div>}
                    <div
                        className={cn(
                            'flex items-center gap-2 px-2 py-1',
                            !minimal && 'border border-accent rounded-sm'
                        )}
                    >
                        <div className="relative flex items-center justify-center">
                            <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                            <div className="w-2 h-2 bg-accent rounded-full" />
                        </div>
                        <span className="text-sm text-accent">Waiting for {listeningForName}s</span>
                    </div>
                </div>
            )}
        </div>
    )
}

export function AdblockWarning({ adblockResult }: { adblockResult: AdblockDetectionResult }): JSX.Element | null {
    if (adblockResult !== 'blocked') {
        return null
    }

    return (
        <div className="flex items-start gap-2 px-3 py-2 rounded border border-warning bg-warning-highlight text-sm">
            <IconWarning className="text-warning mt-0.5 shrink-0" />
            <span>
                Your install might be working fine, but it looks like this browser may be blocking PostHog requests. Try
                disabling your adblocker and refreshing the page to verify. You can set up a reverse proxy later to
                ensure events aren't blocked for your users.
            </span>
        </div>
    )
}
