import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { elapsedSecondsFrom } from 'lib/utils/datetime'

import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { activeCloudRunLogic, CloudRunHandle } from './activeCloudRunLogic'
import { finishedLocalRunLogic } from './finishedLocalRunLogic'
import { formatElapsed, syncHeadline, toneTextClass } from './helpers'
import {
    InstallationProgress,
    installationProgressLogic,
    progressFromFinishedLocalRun,
} from './installationProgressLogic'
import { InstallationProgressContent } from './InstallationProgressView'
import { wizardActiveSessionDetectorLogic } from './wizardActiveSessionDetectorLogic'
import { DetectedDashboard, wizardDashboardLogic } from './wizardDashboardLogic'
import { StatusGlyph, WizardSyncCard, WizardSyncMode } from './WizardSyncCard'
import { wizardSyncUiLogic } from './wizardSyncUiLogic'

// Corner anchor for the collapsed card and the minimized launcher. The dialog is a portal, so it
// positions itself.
const CORNER = 'fixed bottom-5 right-5 z-[60]'

// 1Hz clock for the elapsed timer, scoped to a mounted run so nothing ticks when no run is active.
// `frozen` stops the interval entirely — a finished run shows its fixed duration, so ticking for it
// would be pure re-render churn.
function useNow(frozen: boolean = false): number {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        if (frozen) {
            return
        }
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [frozen])
    return now
}

// The minimized state: a small pill that restores the card. This is the "activate it back" affordance.
function WizardSyncLauncher({
    progress,
    elapsedSeconds,
    onRestore,
}: {
    progress: InstallationProgress
    elapsedSeconds: number
    onRestore: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onRestore}
            aria-label="Show PostHog setup progress"
            data-attr="wizard-sync-launcher"
            className={cn(
                'flex items-center gap-2 rounded-full bg-surface-primary border shadow-lg shadow-black/10 pl-2 pr-3 py-1.5 hover:bg-fill-highlight-50 transition-colors cursor-pointer',
                // A minimized run that finished (or failed) should read at a glance, not hide as a
                // neutral pill.
                progress.phase === 'completed'
                    ? 'border-success'
                    : progress.phase === 'error'
                      ? 'border-danger'
                      : 'border-primary'
            )}
        >
            <StatusGlyph progress={progress} />
            <span className="text-sm font-medium">PostHog setup</span>
            <span className="text-xs text-muted tabular-nums">{formatElapsed(elapsedSeconds)}</span>
        </button>
    )
}

// The expanded "all the details" dialog: the full pipeline plus the terminal payoff or failure.
function WizardSyncDialog({
    progress,
    elapsedSeconds,
    mode,
    dashboard,
    isOpen,
    onClose,
    onClear,
    onDashboardClick,
}: {
    progress: InstallationProgress
    elapsedSeconds: number
    mode: WizardSyncMode
    dashboard?: DetectedDashboard | null
    isOpen: boolean
    onClose: () => void
    onClear?: () => void
    onDashboardClick?: () => void
}): JSX.Element {
    const isTerminal = progress.phase === 'completed' || progress.phase === 'error'
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="PostHog setup" width={480}>
            <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between text-xs">
                    <span className={cn('font-medium', toneTextClass(progress))}>{syncHeadline(progress)}</span>
                    <span className="text-muted tabular-nums">
                        {mode === 'cloud' ? 'Cloud run' : 'On your machine'} · {formatElapsed(elapsedSeconds)}
                    </span>
                </div>
                <InstallationProgressContent
                    progress={progress}
                    mode={mode}
                    dashboard={dashboard}
                    onDashboardClick={onDashboardClick}
                />
                {isTerminal && onClear && (
                    <LemonButton type="secondary" onClick={onClear} className="self-end">
                        Dismiss this run
                    </LemonButton>
                )}
            </div>
        </LemonModal>
    )
}

// Shared presentation for a single run: the collapsed card or, once dismissed, the launcher, plus the
// dialog. Owns the elapsed clock and reads the shared dismiss/expand UI state.
function WizardSyncSurface({
    progress,
    startedAt,
    endedAt,
    mode,
    runKey,
    onClear,
}: {
    progress: InstallationProgress
    startedAt: string | undefined
    /** When the run finished — freezes the elapsed timer so a finished run that stays on screen
     * until dismissed shows its duration, not a clock that keeps counting. */
    endedAt?: string
    mode: WizardSyncMode
    runKey: string
    onClear?: () => void
}): JSX.Element {
    const { dismissedKey, dialogOpen } = useValues(wizardSyncUiLogic)
    const { dismiss, restore, openDialog, closeDialog } = useActions(wizardSyncUiLogic)
    const {
        reportWizardSyncExpanded,
        reportWizardSyncMinimized,
        reportWizardSyncRestored,
        reportWizardSyncRunDismissed,
        reportWizardSyncHandoffShown,
        reportWizardSyncDashboardCtaShown,
        reportWizardSyncDashboardCtaClicked,
    } = useActions(onboardingEventUsageLogic)
    const { detectedDashboard } = useValues(wizardDashboardLogic)
    const endMs = endedAt ? new Date(endedAt).getTime() : NaN
    const now = useNow(!Number.isNaN(endMs))
    const elapsedSeconds = startedAt ? elapsedSecondsFrom(startedAt, Number.isNaN(endMs) ? now : endMs) : 0
    const minimized = dismissedKey === runKey
    const isTerminal = progress.phase === 'completed' || progress.phase === 'error'
    const dashboard = progress.phase === 'completed' ? detectedDashboard : null
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
    const dashboardVisible = !!dashboard
    useEffect(() => {
        if (dashboardVisible) {
            reportWizardSyncDashboardCtaShown({ runKey, mode, surface: 'fab' })
        }
    }, [dashboardVisible, runKey, mode, reportWizardSyncDashboardCtaShown])
    const handleDashboardClick = (): void => reportWizardSyncDashboardCtaClicked({ runKey, mode, surface: 'fab' })
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

    return (
        <>
            <div className={CORNER}>
                {minimized ? (
                    <WizardSyncLauncher
                        progress={progress}
                        elapsedSeconds={elapsedSeconds}
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
                        dashboard={dashboard}
                        onDashboardClick={handleDashboardClick}
                        onExpand={() => {
                            reportWizardSyncExpanded(eventProps)
                            openDialog()
                        }}
                        // Mid-run, the X only minimizes — hiding a live run for good would orphan
                        // it. Once the run is terminal or the PR exists, the user's part is done,
                        // so the X becomes the real dismissal (the run never leaves on its own).
                        onDismiss={(isTerminal || prOpened) && handleClear ? handleClear : handleMinimize}
                        dismissTooltip={(isTerminal || prOpened) && handleClear ? 'Dismiss' : 'Minimize'}
                    />
                )}
            </div>
            <WizardSyncDialog
                progress={progress}
                elapsedSeconds={elapsedSeconds}
                mode={mode}
                dashboard={dashboard}
                onDashboardClick={handleDashboardClick}
                isOpen={dialogOpen}
                onClose={closeDialog}
                onClear={handleClear}
            />
        </>
    )
}

// A cloud run: the Installation layer streams the pipeline; elapsed comes from the handle's kickoff stamp.
function WizardSyncCloudFab({ handle }: { handle: CloudRunHandle }): JSX.Element {
    const { installationProgress, taskRunState } = useValues(
        installationProgressLogic({ mode: 'cloud', runId: handle.runId, taskId: handle.taskId })
    )
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)
    const isTerminal = installationProgress.phase === 'completed' || installationProgress.phase === 'error'
    return (
        <WizardSyncSurface
            progress={installationProgress}
            startedAt={handle.startedAt}
            endedAt={isTerminal ? (taskRunState?.completed_at ?? taskRunState?.updated_at) : undefined}
            mode="cloud"
            runKey={handle.runId}
            onClear={clearActiveCloudRun}
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
function WizardSyncLocalFab(): JSX.Element | null {
    const { installationProgress, latestSession } = useValues(installationProgressLogic({ mode: 'local' }))
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
    const { shouldStream } = useValues(wizardActiveSessionDetectorLogic)
    if (!shouldStream) {
        return <WizardSyncFinishedLocalFab />
    }
    return <WizardSyncLocalFab />
}

/**
 * The single detached wizard sync widget, mounted app-wide (AuthenticatedShell). It surfaces whichever
 * run is in flight, cloud or local, in one place: a cloud run (the persisted handle) takes precedence,
 * otherwise a local wizard session detected by the poll, otherwise a finished local run the user has
 * not yet dismissed. Replaces the earlier separate cloud-run and per-mode corner widgets so there is
 * one corner widget, never two.
 */
export function WizardSyncFab(): JSX.Element | null {
    const syncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    const { activeCloudRun, panelMounted } = useValues(activeCloudRunLogic)

    // An inline install-step progress view is already showing this run, so stay out of its way. The FAB
    // is for after the user moves on from the install step. Both inline views (cloud and local) claim
    // panelMounted, so the run is never shown in two places.
    if (panelMounted) {
        return null
    }
    // Deliberately not gated on the cloud-run flag: a persisted handle is proof the run started
    // while the user was on the test arm, and a mid-experiment flag change must not strand an
    // in-flight run with no surface (and no way to dismiss it). Only STARTING runs is flag-gated.
    if (activeCloudRun) {
        return <WizardSyncCloudFab handle={activeCloudRun} />
    }
    if (syncEnabled) {
        return <WizardSyncLocalGate />
    }
    // Same reasoning as the cloud handle: a persisted finished run is proof it happened under the
    // test arm, and it must stay dismissible if the flag flips mid-experiment.
    return <WizardSyncFinishedLocalFab />
}
