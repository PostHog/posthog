import { IconCheck } from '@posthog/icons'

import { OnboardingLiveEvents } from './OnboardingLiveEvents'
import { useInstallationComplete } from './hooks/useInstallationComplete'

export type RealtimeCheckIndicatorProps = {
    teamPropertyToVerify: string
    listeningForName?: string
}

export function RealtimeCheckIndicator({
    teamPropertyToVerify,
    listeningForName = 'event',
}: RealtimeCheckIndicatorProps): JSX.Element {
    const installationComplete = useInstallationComplete(teamPropertyToVerify)

    return (
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
    )
}
