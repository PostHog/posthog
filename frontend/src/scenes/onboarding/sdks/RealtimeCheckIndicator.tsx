import { IconCheck } from '@posthog/icons'

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
            <span className="hidden sm:block text-sm font-medium">Verify Installation</span>
            {installationComplete ? (
                <div className="flex items-center bg-bg-light dark:bg-bg-depth gap-2 px-2 py-1 border rounded-sm">
                    <IconCheck className="text-success" />
                    <span className="text-success text-sm">Installation Complete</span>
                </div>
            ) : (
                <div className="flex items-center gap-2 px-2 py-1 border border-accent-primary rounded-sm">
                    <div className="relative flex items-center justify-center">
                        <div className="absolute w-3 h-3 border-2 border-accent-primary rounded-full animate-ping" />
                        <div className="w-2 h-2 bg-accent-primary rounded-full" />
                    </div>
                    <span className="text-sm text-accent-primary">Waiting for {listeningForName}s</span>
                </div>
            )}
        </div>
    )
}
