import { IconCheck } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { useInterval } from 'lib/hooks/useInterval'
import React from 'react'
import { teamLogic } from 'scenes/teamLogic'

export type RealtimeCheckIndicatorProps = {
    teamPropertyToVerify: string
    listeningForName?: string
}

export function RealtimeCheckIndicator({
    teamPropertyToVerify,
    listeningForName = 'event',
}: RealtimeCheckIndicatorProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)

    useInterval(() => {
        if (!currentTeam?.[teamPropertyToVerify]) {
            loadCurrentTeam()
        }
    }, 2000)

    const installationComplete = Boolean(currentTeam?.[teamPropertyToVerify]) || true

    return (
        <div className="flex items-center gap-3">
            <span className="text-sm font-medium">Verify Installation</span>
            {installationComplete ? (
                <div className="flex items-center gap-2 px-2 py-1 border rounded-sm">
                    <IconCheck className="text-success" />
                    <span className="text-success text-sm">Installation Complete</span>
                </div>
            ) : (
                <div className="flex items-center gap-2 px-2 py-1 border border-accent-primary rounded-sm">
                    <div className="relative flex items-center justify-center">
                        <div className="absolute w-4 h-4 border-2 border-accent-primary rounded-full animate-ping" />
                        <div className="w-3 h-3 bg-accent-primary rounded-full" />
                    </div>
                    <span className="text-sm text-accent-primary">Waiting for {listeningForName}s...</span>
                </div>
            )}
        </div>
    )
}
