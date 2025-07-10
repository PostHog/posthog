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
                <div className="flex flex-row items-center gap-3">
                    <div className="font-medium">Verify Installation</div>
                    <div className="border-accent flex items-center gap-2 rounded-sm border px-2 py-1">
                        <div className="relative flex items-center justify-center">
                            <div className="border-accent absolute h-3 w-3 animate-ping rounded-full border-2" />
                            <div className="bg-accent h-2 w-2 rounded-full" />
                        </div>
                        <span className="text-accent text-sm">Waiting for {listeningForName}s</span>
                    </div>
                </div>
            )}
        </div>
    )
}
