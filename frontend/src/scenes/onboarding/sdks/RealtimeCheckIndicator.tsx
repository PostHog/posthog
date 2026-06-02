import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { type AdblockDetectionResult } from './hooks/useAdblockDetection'
import { useInstallationComplete } from './hooks/useInstallationComplete'
import { OnboardingLiveEvents } from './OnboardingLiveEvents'

export type RealtimeCheckIndicatorProps = {
    teamPropertyToVerify: string
    listeningForName?: string
}

export function RealtimeCheckIndicator({
    teamPropertyToVerify,
    listeningForName = 'event',
}: RealtimeCheckIndicatorProps): JSX.Element {
    const installationComplete = useInstallationComplete(teamPropertyToVerify)
    const { loadCurrentTeam } = useActions(teamLogic)
    const [isRechecking, setIsRechecking] = useState(false)
    const recheckTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

    useEffect(() => () => clearTimeout(recheckTimeoutRef.current), [])

    if (installationComplete) {
        return (
            <div className="flex items-center gap-3">
                <div className="flex flex-row gap-2">
                    <div className="flex items-center gap-2 px-2 py-1 font-medium">
                        <IconCheck className="text-success" />
                        <span className="text-success text-sm">Installation complete</span>
                    </div>
                    <OnboardingLiveEvents />
                </div>
            </div>
        )
    }

    // Verification happens automatically as the team polls for its first event, but the click here
    // gives an explicit "check now" affordance so the indicator doesn't read as a dead button.
    const handleRecheck = (): void => {
        loadCurrentTeam()
        setIsRechecking(true)
        clearTimeout(recheckTimeoutRef.current)
        recheckTimeoutRef.current = setTimeout(() => setIsRechecking(false), 1500)
    }

    return (
        <div className="flex items-center gap-3">
            <div className="flex flex-row gap-3 items-center">
                <div className="font-medium">Verify installation</div>
                <Tooltip
                    title={`We're automatically listening for your first ${listeningForName}. This completes on its own once your app runs and sends ${listeningForName}s — for mobile and server SDKs that can take a moment after you build and run. Click to check now.`}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={handleRecheck}
                        loading={isRechecking}
                        icon={
                            isRechecking ? undefined : (
                                <div className="relative flex items-center justify-center">
                                    <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                                    <div className="w-2 h-2 bg-accent rounded-full" />
                                </div>
                            )
                        }
                    >
                        <span className="text-sm text-accent">
                            {isRechecking ? 'Checking…' : `Waiting for ${listeningForName}s`}
                        </span>
                    </LemonButton>
                </Tooltip>
            </div>
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
