import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { userLogic } from 'scenes/userLogic'

import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { isRunStale, resolveStartedByLabel } from './helpers'
import { useNow } from './hooks'
import { InstallationProgress } from './installationProgressLogic'
import { WizardSyncCard, WizardSyncMode } from './WizardSyncCard'
import { WizardSyncDialog } from './WizardSyncDialog'
import { WizardSyncLauncher } from './WizardSyncLauncher'
import { wizardSyncUiLogic } from './wizardSyncUiLogic'

// Corner anchor for the collapsed card and the minimized launcher. The dialog is a portal, so it
// positions itself.
const CORNER = 'fixed bottom-5 right-5 z-[60]'

// Shared presentation for a single run: the collapsed card or, once dismissed, the launcher, plus the
// dialog. Owns the elapsed clock and reads the shared dismiss/expand UI state.
export function WizardSyncSurface({
    progress,
    startedAt,
    endedAt,
    lastActivityAt = null,
    streamLost = false,
    mode,
    runKey,
    onClear,
    onCancel,
    cancelling = false,
}: {
    progress: InstallationProgress
    startedAt: string | undefined
    /** When the run finished — freezes the elapsed timer so a finished run that stays on screen
     * until dismissed shows its duration, not a clock that keeps counting. */
    endedAt?: string
    /** When the run's stream last delivered anything (cloud runs only), for the staleness check. */
    lastActivityAt?: number | null
    /** Nothing is currently carrying this run's updates (cloud runs only): the stream failed or
     * closed, or the logic has already given up on it. Silence only counts as staleness while this
     * holds. See `isStreamLost` for why a stream still connecting does not qualify. */
    streamLost?: boolean
    mode: WizardSyncMode
    runKey: string
    onClear?: () => void
    /** Cancels the run server-side (cloud runs only) — shown in the dialog while the run is live. */
    onCancel?: () => void
    cancelling?: boolean
}): JSX.Element {
    const { dismissedKey, dialogOpen } = useValues(wizardSyncUiLogic)
    const { dismiss, restore, openDialog, closeDialog, openHandoffDoc } = useActions(wizardSyncUiLogic)
    const { user } = useValues(userLogic)
    const startedByLabel = resolveStartedByLabel(progress.startedBy, user?.email)
    const {
        reportWizardSyncExpanded,
        reportWizardSyncMinimized,
        reportWizardSyncRestored,
        reportWizardSyncRunDismissed,
        reportWizardSyncHandoffShown,
        reportWizardSyncHandoffDocOpened,
    } = useActions(onboardingEventUsageLogic)
    // `now` also feeds the staleness check, which needs a live clock while the run is non-terminal.
    const endMs = endedAt ? new Date(endedAt).getTime() : NaN
    const now = useNow(!Number.isNaN(endMs))
    const elapsedSeconds = startedAt ? elapsedSecondsFrom(startedAt, Number.isNaN(endMs) ? now : endMs) : 0
    // Input-required overrides minimize: the user who tucked the widget away mid-run is exactly the
    // one who will miss the prompt. The server clearing pending_input restores their choice.
    const minimized = dismissedKey === runKey && !progress.pendingInput
    const isTerminal = progress.phase === 'completed' || progress.phase === 'error'
    // Only cloud runs can zombie like this: their handle is persisted browser state that outlives the
    // run, where a local run is gated by the session detector's own liveness poll.
    const stale = mode === 'cloud' && !isTerminal && isRunStale(startedAt, lastActivityAt, streamLost, now)
    const eventProps = { runKey, mode, phase: progress.phase }

    // The completed-handoff funnel (exposure + CTA impression) — deduped per run inside the events
    // logic, so this fires safely even when the inline panel reported the same run first.
    const completed = progress.phase === 'completed'
    const prOpened = !!progress.prUrl
    useEffect(() => {
        if (completed) {
            reportWizardSyncHandoffShown({ runKey, mode, surface: 'fab', prOpened })
        }
    }, [completed, runKey, mode, prOpened, reportWizardSyncHandoffShown])
    const handoffText = progress.handoffText
    const handleViewReport = handoffText
        ? () => {
              reportWizardSyncHandoffDocOpened({ runKey, mode, trigger: 'button' })
              openHandoffDoc({ key: runKey, text: handoffText })
          }
        : undefined
    // One-shot: a double-click can land two dispatches before the surface unmounts, which would
    // double-fire the dismissal telemetry and re-run onClear.
    const clearedRef = useRef(false)
    // Clearing a finished run also closes the dialog before the surface unmounts.
    const handleClear = onClear
        ? () => {
              if (clearedRef.current) {
                  return
              }
              clearedRef.current = true
              reportWizardSyncRunDismissed({ ...eventProps, elapsedSeconds })
              closeDialog()
              onClear()
          }
        : undefined
    const handleMinimize = (): void => {
        reportWizardSyncMinimized(eventProps)
        dismiss(runKey)
    }
    const dismissible = isTerminal || prOpened || stale

    return (
        <>
            <div className={CORNER}>
                {minimized ? (
                    <WizardSyncLauncher
                        progress={progress}
                        elapsedSeconds={elapsedSeconds}
                        stale={stale}
                        onRestore={() => {
                            reportWizardSyncRestored(eventProps)
                            restore()
                        }}
                    />
                ) : (
                    <WizardSyncCard
                        progress={progress}
                        elapsedSeconds={elapsedSeconds}
                        mode={mode}
                        stale={stale}
                        startedByLabel={startedByLabel}
                        onViewReport={handleViewReport}
                        onExpand={() => {
                            reportWizardSyncExpanded(eventProps)
                            openDialog()
                        }}
                        // Mid-run the X only minimizes, since hiding a live run for good would
                        // orphan it. Once the run is terminal, the PR exists, or the run has gone
                        // quiet long enough to count as stale, the X becomes the real dismissal
                        // (the run never leaves on its own).
                        onDismiss={dismissible && handleClear ? handleClear : handleMinimize}
                        dismissTooltip={dismissible && handleClear ? 'Dismiss' : 'Minimize'}
                    />
                )}
            </div>
            <WizardSyncDialog
                progress={progress}
                elapsedSeconds={elapsedSeconds}
                mode={mode}
                stale={stale}
                startedByLabel={startedByLabel}
                onViewReport={handleViewReport}
                isOpen={dialogOpen}
                onClose={closeDialog}
                onClear={handleClear}
                onCancel={onCancel}
                cancelling={cancelling}
            />
        </>
    )
}
