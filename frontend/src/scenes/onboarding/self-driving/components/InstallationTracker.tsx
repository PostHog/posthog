import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { elapsedLabel, resolveStartedByLabel, syncHeadline, toneTextClass } from '../../shared/wizard-sync/helpers'
import { useRunElapsedSeconds } from '../../shared/wizard-sync/hooks'
import { installationProgressLogic } from '../../shared/wizard-sync/installationProgressLogic'
import { StatusGlyph } from '../../shared/wizard-sync/StatusGlyph'
import {
    watchWorkflowWhileMounted,
    wizardActiveSessionDetectorLogic,
} from '../../shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { WizardSyncDialog } from '../../shared/wizard-sync/WizardSyncDialog'
import { wizardSyncUiLogic } from '../../shared/wizard-sync/wizardSyncUiLogic'
import { SELF_DRIVING_WORKFLOW_ID } from '../../shared/wizard-sync/workflows'

/**
 * The self-driving flow's in-card run tracker: a compact clickable summary of the wizard run that
 * opens the full progress dialog. `card` replaces the install step's command block while the run is
 * going; `pill` sits in the flow header on the steps after it. The onboarding shows the run through
 * these (and claims the inline panel), so the corner FAB never appears here.
 */
export function InstallationTracker({ variant }: { variant: 'card' | 'pill' }): JSX.Element | null {
    const { installationProgress, latestSession } = useValues(
        installationProgressLogic({ mode: 'local', workflowId: SELF_DRIVING_WORKFLOW_ID })
    )
    const { dialogOpen } = useValues(wizardSyncUiLogic)
    const { openDialog, closeDialog, openHandoffDoc } = useActions(wizardSyncUiLogic)
    const { user } = useValues(userLogic)

    const isTerminal = installationProgress.phase === 'completed' || installationProgress.phase === 'error'
    const elapsedSeconds = useRunElapsedSeconds(
        latestSession?.started_at,
        isTerminal ? latestSession?.updated_at : undefined
    )

    if (!installationProgress.isCurrent) {
        return null
    }

    const handoffText = installationProgress.handoffText
    const runKey = latestSession?.session_id
    const handleViewReport =
        handoffText && runKey ? () => openHandoffDoc({ key: runKey, text: handoffText }) : undefined

    return (
        <>
            {variant === 'card' ? (
                <button
                    type="button"
                    onClick={openDialog}
                    data-attr="self-driving-installation-tracker-card"
                    className="OnboardingProductCard w-full flex items-center gap-3 p-4 rounded-lg border text-left cursor-pointer transition-all hover:shadow-sm"
                >
                    <StatusGlyph progress={installationProgress} />
                    <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                        <span className="text-sm font-semibold">PostHog setup</span>
                        <span className={cn('text-xs', toneTextClass(installationProgress))}>
                            {syncHeadline(installationProgress)}
                        </span>
                    </div>
                    <span className="text-xs text-muted tabular-nums shrink-0">{elapsedLabel(elapsedSeconds)}</span>
                </button>
            ) : (
                <button
                    type="button"
                    onClick={openDialog}
                    aria-label="Show PostHog setup progress"
                    data-attr="self-driving-installation-tracker-pill"
                    className="flex items-center gap-1.5 rounded-full border bg-surface-primary pl-1.5 pr-2.5 py-1 hover:bg-fill-highlight-50 transition-colors cursor-pointer"
                >
                    <StatusGlyph progress={installationProgress} />
                    <span className="text-xs text-muted tabular-nums whitespace-nowrap">
                        {elapsedLabel(elapsedSeconds)}
                    </span>
                </button>
            )}
            <WizardSyncDialog
                progress={installationProgress}
                elapsedSeconds={elapsedSeconds}
                mode="local"
                isOpen={dialogOpen}
                onClose={closeDialog}
                onViewReport={handleViewReport}
                startedByLabel={resolveStartedByLabel(installationProgress.startedBy, user?.email)}
            />
        </>
    )
}

/**
 * Gate for surfaces that don't already stream the run (the flow header): opens the session stream
 * only once the cheap detector poll says a self-driving run is in flight.
 */
export function InstallationTrackerGate(): JSX.Element | null {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { shouldStream, activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)
    useEffect(() => watchWorkflowWhileMounted(SELF_DRIVING_WORKFLOW_ID), [])
    if (!shouldStream || activeWorkflowId !== SELF_DRIVING_WORKFLOW_ID) {
        return null
    }
    return <InstallationTracker variant="pill" />
}
