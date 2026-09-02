import { useActions, useValues } from 'kea'
import { type ReactNode, useEffect } from 'react'

import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { finishedLocalRunLogic } from './finishedLocalRunLogic'
import { InstallationProgressContent } from './InstallationProgressContent'
import { installationProgressLogic } from './installationProgressLogic'
import { wizardSyncUiLogic } from './wizardSyncUiLogic'

/**
 * Container: streams a run's progress from the Installation layer and renders it — the same view for
 * both modes, cloud runs just additionally track the TaskRun pipeline (`mode: 'cloud'` with the run
 * handle; `mode: 'local'` reads only the wizard session stream). Inline on the install step (sets
 * the inline-panel claim to hide the detached widget) or inside the FAB itself (`floating`).
 */
export function InstallationProgressView({
    mode,
    runId,
    taskId,
    workflowId,
    continueHint,
    floating = false,
    onDismiss,
    onRetryLocally,
}: {
    mode: 'local' | 'cloud'
    /** The TaskRun handle — required for cloud runs, absent for local ones. */
    runId?: string
    taskId?: string
    /** Wizard program to track. Defaults to the SDK install. */
    workflowId?: string
    /** Shown while the run is in flight, to say it keeps going if the user navigates away. */
    continueHint?: ReactNode
    /** Rendered in the floating FAB rather than inline on the install step. */
    floating?: boolean
    onDismiss?: () => void
    /** Forwarded to the failed-run fallback (see InstallationProgressContent). */
    onRetryLocally?: () => void
}): JSX.Element {
    const { installationProgress, latestSession } = useValues(
        installationProgressLogic({ mode, runId, taskId, workflowId })
    )
    const { claimInlinePanel, releaseInlinePanel, openHandoffDoc } = useActions(wizardSyncUiLogic)
    const { dismissLocalRun } = useActions(finishedLocalRunLogic)
    const { reportWizardSyncHandoffShown, reportWizardSyncHandoffDocOpened } = useActions(onboardingEventUsageLogic)

    // While shown inline on the install step, hide the floating FAB so the same run isn't in two places.
    useEffect(() => {
        if (floating) {
            return
        }
        claimInlinePanel(mode)
        return () => releaseInlinePanel(mode)
    }, [floating, mode, claimInlinePanel, releaseInlinePanel])

    const runKey = mode === 'cloud' ? runId : latestSession?.session_id
    const completed = installationProgress.phase === 'completed'
    const prOpened = !!installationProgress.prUrl

    // The completed-handoff funnel (exposure + CTA impression), deduped per run inside the events
    // logic so remounts and the FAB showing the same run don't double count.
    useEffect(() => {
        if (completed && runKey) {
            reportWizardSyncHandoffShown({ runKey, mode, surface: 'inline', prOpened })
        }
    }, [completed, runKey, mode, prOpened, reportWizardSyncHandoffShown])

    const handoffText = installationProgress.handoffText
    const handleViewReport =
        handoffText && runKey
            ? () => {
                  reportWizardSyncHandoffDocOpened({ runKey, mode, trigger: 'button' })
                  openHandoffDoc({ key: runKey, text: handoffText })
              }
            : undefined

    // Local runs always get a dismissal: it releases the install-step takeover and the FAB in one
    // move, and nothing else knows the session to clear. Cloud dismissal stays with the caller
    // (it owns the persisted run handle).
    const defaultLocalDismiss =
        mode === 'local' && latestSession ? () => dismissLocalRun(latestSession.session_id) : undefined

    return (
        <InstallationProgressContent
            workflowId={workflowId}
            continueHint={continueHint}
            progress={installationProgress}
            mode={mode}
            onViewReport={handleViewReport}
            onDismiss={onDismiss ?? defaultLocalDismiss}
            onRetryLocally={onRetryLocally}
        />
    )
}
