import { IconCheck, IconWarning } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'

import { useAdblockDetection } from './hooks/useAdblockDetection'
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
    const adblockResult = useAdblockDetection()

    const showAdblockWarning = !installationComplete && adblockResult === 'blocked'

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
                {installationComplete ? (
                    <div className="flex flex-row gap-2">
                        <div className="flex items-center gap-2 px-2 py-1 font-medium">
                            <IconCheck className="text-success" />
                            <span className="text-success text-sm">Installation Complete</span>
                        </div>
                        <OnboardingLiveEvents />
                    </div>
                ) : (
                    <div className="flex flex-row gap-3 items-center">
                        <div className="font-medium">Verify Installation</div>
                        <div className="flex items-center gap-2 px-2 py-1 border border-accent rounded-sm">
                            <div className="relative flex items-center justify-center">
                                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                                <div className="w-2 h-2 bg-accent rounded-full" />
                            </div>
                            <span className="text-sm text-accent">Waiting for {listeningForName}s</span>
                        </div>
                    </div>
                )}
            </div>
            {showAdblockWarning && (
                <div className="flex items-start gap-2 px-3 py-2 rounded border border-warning bg-warning-highlight text-sm">
                    <IconWarning className="text-warning mt-0.5 shrink-0" />
                    <span>
                        Your install might be working fine, but it looks like this browser may be blocking PostHog
                        requests. Try disabling your adblocker and refreshing the page to verify.{' '}
                        <Link to="https://posthog.com/docs/advanced/proxy" target="_blank">
                            Set up a reverse proxy
                        </Link>{' '}
                        to ensure events aren't blocked for your users.
                    </span>
                </div>
            )}
        </div>
    )
}
