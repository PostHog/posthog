import { useValues } from 'kea'

import { IconGithub } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { isTerminalStatus } from 'scenes/onboarding/shared/wizard-sync/taskRunStreamLogic'

// Shown to partner-provisioned users while their setup wizard cloud run is in flight. The live
// progress + PR link live in the setup FAB (bottom-right); this card just makes the background
// work legible from inside the welcome dialog and points at it.
export function InstallProgressCard(): JSX.Element | null {
    const { activeCloudRun, serverReportedRun } = useValues(activeCloudRunLogic)

    if (!activeCloudRun) {
        return null
    }
    // The persisted handle survives up to 24h past completion (the server keeps returning terminal
    // runs that long, and activeCloudRunLogic deliberately keeps the handle so the stream's
    // completion handoff isn't dropped), so its presence alone doesn't mean the run is still live.
    if (serverReportedRun?.runId === activeCloudRun.runId && isTerminalStatus(serverReportedRun.status)) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <div className="flex items-start gap-3">
                <IconGithub className="text-2xl shrink-0 mt-0.5" />
                <div>
                    <h2 className="text-lg font-semibold mb-1">We're setting up PostHog in your repo</h2>
                    <p className="text-sm text-muted m-0">
                        A pull request that wires up PostHog is being prepared in the background. Follow its progress in
                        the setup panel in the bottom-right corner - it'll link the pull request as soon as it's open.
                    </p>
                </div>
            </div>
        </LemonCard>
    )
}
