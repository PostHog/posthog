import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { elapsedLabel, localModeLabel, syncHeadline, toneTextClass } from './helpers'
import { InstallationProgressContent } from './InstallationProgressContent'
import { InstallationProgress } from './installationProgressLogic'
import { WizardSyncMode } from './WizardSyncCard'

// The expanded "all the details" dialog: the full pipeline plus the terminal payoff or failure.
// Rendered by the FAB and by the inbox rail's Installation card, which claims the run away from
// the FAB — hence its own file rather than living with either surface.
export function WizardSyncDialog({
    progress,
    elapsedSeconds,
    mode,
    isOpen,
    onClose,
    onClear,
    onCancel,
    onViewReport,
    cancelling = false,
    stale = false,
    startedByLabel,
}: {
    progress: InstallationProgress
    elapsedSeconds: number
    mode: WizardSyncMode
    isOpen: boolean
    onClose: () => void
    onClear?: () => void
    onCancel?: () => void
    /** Opens the run's handoff doc (the setup report) when the progress carries one. */
    onViewReport?: () => void
    cancelling?: boolean
    /** The run has gone quiet for long enough that it can be dismissed without orphaning live work. */
    stale?: boolean
    /** A teammate's name for a local run they started (null when it's the viewer's own run or unknown). */
    startedByLabel?: string | null
}): JSX.Element {
    const isTerminal = progress.phase === 'completed' || progress.phase === 'error'
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="PostHog setup" width={480}>
            <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between text-xs">
                    <span className={cn('font-medium', toneTextClass(progress))}>{syncHeadline(progress)}</span>
                    <span className="text-muted tabular-nums">
                        {mode === 'cloud' ? 'Cloud run' : localModeLabel(startedByLabel)} ·{' '}
                        {elapsedLabel(elapsedSeconds, stale)}
                    </span>
                </div>
                <InstallationProgressContent progress={progress} mode={mode} onViewReport={onViewReport} />
                {/* A stale run gets the same exit as a terminal one: nothing is reporting on it, so
                    leaving Cancel as the only control would strand the user behind a request that
                    cannot bring it back. Cancel stays available below for as long as the run is not
                    terminal, since the backend may still be holding a sandbox for it. */}
                {(isTerminal || stale) && onClear && (
                    <LemonButton type="secondary" onClick={onClear} className="self-end">
                        Dismiss this run
                    </LemonButton>
                )}
                {!isTerminal && onCancel && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={onCancel}
                        loading={cancelling}
                        disabledReason={cancelling ? 'Cancelling the run' : undefined}
                        className="self-end"
                        data-attr="wizard-sync-cancel-run"
                    >
                        Cancel run
                    </LemonButton>
                )}
            </div>
        </LemonModal>
    )
}
