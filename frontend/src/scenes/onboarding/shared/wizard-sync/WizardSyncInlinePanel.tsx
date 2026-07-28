import { useMountedLogic, useValues } from 'kea'
import { type ReactNode } from 'react'

import { InstallationProgressView } from './InstallationProgressView'
import { wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'

/**
 * The live wizard run, rendered where the user already is instead of in the corner widget.
 *
 * Mounting it claims the run (see `wizardSyncUiLogic.inlinePanelMounted`), so the detached FAB and
 * the nav status button stand down for as long as this is on screen. Renders nothing when no run is
 * in flight, so a scene can drop it in unconditionally.
 *
 * Scenes that own the whole "before / during" story — the onboarding install step, which swaps the
 * command block for progress — drive `InstallationProgressView` themselves. This is for scenes that
 * just want to surface a run that happens to be going.
 */
export function WizardSyncInlinePanel({ continueHint }: { continueHint?: ReactNode }): JSX.Element | null {
    // The detector's cheap poll is what tells us a run exists at all; mounting it here means a scene
    // showing this panel doesn't depend on the FAB being rendered to find the run.
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { shouldStream, activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)

    if (!shouldStream || !activeWorkflowId) {
        return null
    }

    return <InstallationProgressView mode="local" workflowId={activeWorkflowId} continueHint={continueHint} />
}
