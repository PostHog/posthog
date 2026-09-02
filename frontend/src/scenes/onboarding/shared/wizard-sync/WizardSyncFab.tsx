import { useActions, useMountedLogic, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { resolveOnboardingFlowVariant } from 'scenes/onboarding/onboardingVariants'

import { activeCloudRunLogic, CloudRunHandle } from './activeCloudRunLogic'
import { finishedLocalRunLogic } from './finishedLocalRunLogic'
import { isStreamLost } from './helpers'
import { progressFromFinishedLocalRun } from './installationProgress'
import { installationProgressLogic } from './installationProgressLogic'
import { wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'
import { WizardSyncSurface } from './WizardSyncSurface'
import { wizardSyncUiLogic } from './wizardSyncUiLogic'

// A cloud run: the Installation layer streams the pipeline; elapsed comes from the handle's kickoff stamp.
function WizardSyncCloudFab({ handle }: { handle: CloudRunHandle }): JSX.Element {
    const { installationProgress, taskRunState, lastActivityAt, taskConnectionStatus, isStalled } = useValues(
        installationProgressLogic({ mode: 'cloud', runId: handle.runId, taskId: handle.taskId })
    )
    const { cancellingRun } = useValues(activeCloudRunLogic)
    const { clearActiveCloudRun, cancelActiveCloudRun } = useActions(activeCloudRunLogic)
    const isTerminal = installationProgress.phase === 'completed' || installationProgress.phase === 'error'
    return (
        <WizardSyncSurface
            progress={installationProgress}
            startedAt={handle.startedAt}
            endedAt={isTerminal ? (taskRunState?.completed_at ?? taskRunState?.updated_at) : undefined}
            lastActivityAt={lastActivityAt}
            streamLost={isStreamLost(taskConnectionStatus, isStalled)}
            mode="cloud"
            runKey={handle.runId}
            onClear={clearActiveCloudRun}
            onCancel={cancelActiveCloudRun}
            cancelling={cancellingRun}
        />
    )
}

// A finished local run rendered from its persisted snapshot: the session stream gates itself off
// shortly after a terminal phase (INC-886), but the handoff stays until the user dismisses it.
function WizardSyncFinishedLocalFab(): JSX.Element | null {
    const { finishedLocalRun } = useValues(finishedLocalRunLogic)
    const { dismissLocalRun } = useActions(finishedLocalRunLogic)
    if (!finishedLocalRun) {
        return null
    }
    return (
        <WizardSyncSurface
            progress={progressFromFinishedLocalRun(finishedLocalRun)}
            startedAt={finishedLocalRun.startedAt}
            endedAt={finishedLocalRun.finishedAt}
            mode="local"
            runKey={finishedLocalRun.sessionId}
            onClear={() => dismissLocalRun(finishedLocalRun.sessionId)}
        />
    )
}

// A live local run: the wizard session stream is the source; elapsed comes from its started_at.
function WizardSyncLocalFab({ workflowId }: { workflowId: string }): JSX.Element | null {
    const { installationProgress, latestSession } = useValues(installationProgressLogic({ mode: 'local', workflowId }))
    const { dismissedSessionId } = useValues(finishedLocalRunLogic)
    const { dismissLocalRun } = useActions(finishedLocalRunLogic)
    // No session on the stream yet, or the user already dismissed this one — fall back to the
    // persisted finished run (if any) rather than rendering nothing.
    if (!latestSession || latestSession.session_id === dismissedSessionId) {
        return <WizardSyncFinishedLocalFab />
    }
    const isTerminal = installationProgress.phase === 'completed' || installationProgress.phase === 'error'
    return (
        <WizardSyncSurface
            progress={installationProgress}
            startedAt={latestSession.started_at}
            endedAt={isTerminal ? latestSession.updated_at : undefined}
            mode="local"
            runKey={latestSession.session_id}
            onClear={() => dismissLocalRun(latestSession.session_id)}
        />
    )
}

// Gate the local SSE behind the cheap detector poll, so a stream is opened only when a run is in
// flight. Once the detector gates the stream off (terminal grace expired), the persisted finished
// run keeps the handoff on screen without any stream.
function WizardSyncLocalGate(): JSX.Element | null {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    // Stream whichever program the detector found live, so a self-driving run is surfaced by the
    // same widget rather than being mistaken for an SDK install (or missed entirely).
    const { shouldStream, activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)
    if (!shouldStream || !activeWorkflowId) {
        return <WizardSyncFinishedLocalFab />
    }
    return <WizardSyncLocalFab workflowId={activeWorkflowId} />
}

/**
 * The single detached wizard sync widget, mounted app-wide (AuthenticatedShell). It surfaces whichever
 * run is in flight, cloud or local, in one place: a cloud run (the persisted handle) takes precedence,
 * otherwise a local wizard session detected by the poll, otherwise a finished local run the user has
 * not yet dismissed. Replaces the earlier separate cloud-run and per-mode corner widgets so there is
 * one corner widget, never two.
 */
export function WizardSyncFab(): JSX.Element | null {
    const syncFlagEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { inlineCloudPanelMounted, inlineLocalPanelMounted } = useValues(wizardSyncUiLogic)
    // The self-driving onboarding syncs unconditionally, so its users need the detached widget too
    // once they navigate away from the install step — the sync flag only gates the legacy arm.
    const syncEnabled = syncFlagEnabled || resolveOnboardingFlowVariant(featureFlags) === 'self-driving'

    // Deliberately not gated on the cloud-run flag: a persisted handle is proof the run started
    // while the user was on the test arm, and a mid-experiment flag change must not strand an
    // in-flight run with no surface (and no way to dismiss it). Only STARTING runs is flag-gated.
    // Checked before the inline-panel claim because that claim is made by surfaces that only ever
    // render the *local* run: letting it win here would leave a concurrent cloud run with no
    // progress, no cancel and no dismiss for as long as the inline surface is open.
    if (activeCloudRun && !inlineCloudPanelMounted) {
        return <WizardSyncCloudFab handle={activeCloudRun} />
    }
    // An inline install-step progress view is already showing this run, so stay out of its way. The FAB
    // is for after the user moves on from the install step. Both inline views (cloud and local) claim
    // the inline-panel claim, so the run is never shown in two places.
    if (inlineLocalPanelMounted || (activeCloudRun && inlineCloudPanelMounted)) {
        return null
    }
    if (syncEnabled) {
        return <WizardSyncLocalGate />
    }
    // Same reasoning as the cloud handle: a persisted finished run is proof it happened under the
    // test arm, and it must stay dismissible if the flag flips mid-experiment.
    return <WizardSyncFinishedLocalFab />
}
