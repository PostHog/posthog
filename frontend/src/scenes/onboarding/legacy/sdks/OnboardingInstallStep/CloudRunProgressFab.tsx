import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { activeCloudRunLogic, CloudRunHandle } from './activeCloudRunLogic'
import { InstallationProgressView } from './InstallationProgressView'
import { installationProgressLogic } from './installationProgressLogic'

/**
 * Floating progress widget for a cloud installation run, mounted app-wide (AuthenticatedShell) so the
 * run stays visible after the user advances past the install step. Renders the Installation layer's
 * progress; hides while the inline view on the install step is mounted (panelMounted) so the same run
 * isn't shown in two places. The legacy WizardProgressFab (local wizard sessions) suppresses itself
 * while a cloud run is active, so only one floating widget shows even though the cloud wizard posts to
 * the same wizard session.
 */
export function CloudRunProgressFab(): JSX.Element | null {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { activeCloudRun, panelMounted } = useValues(activeCloudRunLogic)

    if (!cloudRunEnabled || !activeCloudRun || panelMounted) {
        return null
    }
    return <CloudRunProgressFabInner handle={activeCloudRun} />
}

function CloudRunProgressFabInner({ handle }: { handle: CloudRunHandle }): JSX.Element {
    const { installationProgress } = useValues(
        installationProgressLogic({ mode: 'cloud', runId: handle.runId, taskId: handle.taskId })
    )
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)

    // Only let the user dismiss a finished run — a still-running one stays put so they don't lose track.
    const isTerminal = installationProgress.phase === 'completed' || installationProgress.phase === 'error'

    return (
        <div className="fixed bottom-5 right-5 z-[60] w-[340px]">
            <InstallationProgressView
                runId={handle.runId}
                taskId={handle.taskId}
                floating
                onDismiss={isTerminal ? clearActiveCloudRun : undefined}
            />
        </div>
    )
}
