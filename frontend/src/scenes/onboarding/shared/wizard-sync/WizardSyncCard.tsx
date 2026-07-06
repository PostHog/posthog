import {
    IconCheckCircle,
    IconCloud,
    IconExpand45,
    IconLaptop,
    IconPullRequest,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { currentTaskLabel, formatElapsed, pipClass, stepCounts, syncHeadline, toneTextClass } from './helpers'
import { InstallationProgress } from './installationProgressLogic'

export type WizardSyncMode = 'cloud' | 'local'

// Leading glyph for the prominent task line: it carries the run's tone (accent while working, green on
// success, red on failure). Shared with the launcher and dialog.
export function StatusGlyph({ progress }: { progress: InstallationProgress }): JSX.Element {
    if (progress.phase === 'completed') {
        return <IconCheckCircle className="text-success text-xl shrink-0" />
    }
    if (progress.phase === 'error') {
        return <IconWarning className="text-danger text-xl shrink-0" />
    }
    return <Spinner className="text-xl shrink-0 text-accent" textColored />
}

// Tiny chip naming where the run is happening, so cloud and local runs read distinctly.
function ModeChip({ mode }: { mode: WizardSyncMode }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1 text-xs text-muted">
            {mode === 'cloud' ? <IconCloud className="text-sm" /> : <IconLaptop className="text-sm" />}
            {mode === 'cloud' ? 'Cloud run' : 'On your machine'}
        </span>
    )
}

/**
 * The collapsed detached widget: the wizard's current task takes top billing, with the phase, where it
 * is running, elapsed time, and a per-step pip strip as supporting context. Pure and position-agnostic
 * (the FAB wrapper pins it to the corner) so every state is storyable. Clicking the body, or the expand
 * control, opens the full dialog.
 */
export function WizardSyncCard({
    progress,
    elapsedSeconds,
    mode,
    onExpand,
    onDismiss,
}: {
    progress: InstallationProgress
    elapsedSeconds: number
    mode: WizardSyncMode
    onExpand: () => void
    onDismiss?: () => void
}): JSX.Element {
    const { completed, total } = stepCounts(progress.steps)
    const task = currentTaskLabel(progress)
    const isRunning = progress.phase !== 'completed' && progress.phase !== 'error'

    return (
        <div
            className="w-[340px] bg-surface-primary rounded-xl border border-primary shadow-xl shadow-black/10 overflow-hidden"
            role="status"
            aria-live="polite"
            data-attr="wizard-sync-card"
        >
            <button
                type="button"
                onClick={onExpand}
                aria-label="Expand setup details"
                className="w-full text-left flex flex-col gap-2.5 px-3.5 py-3 hover:bg-fill-highlight-50 transition-colors cursor-pointer"
            >
                <div className="flex items-center gap-2.5">
                    <StatusGlyph progress={progress} />
                    <div className="flex-1 min-w-0">
                        <p
                            className={cn('m-0 text-sm font-semibold truncate', toneTextClass(progress))}
                            title={task ?? undefined}
                        >
                            {task}
                        </p>
                        <p className="m-0 text-xs text-muted truncate">{syncHeadline(progress)}</p>
                    </div>
                    <span className="text-xs text-muted tabular-nums shrink-0">{formatElapsed(elapsedSeconds)}</span>
                </div>

                {total > 0 ? (
                    <div className="flex items-center gap-2">
                        <div className="flex flex-1 items-center gap-1">
                            {progress.steps.map((step) => (
                                <span key={step.id} className={cn('h-1 flex-1 rounded-full', pipClass(step.status))} />
                            ))}
                        </div>
                        <span className="text-xs text-muted tabular-nums shrink-0">
                            {completed}/{total}
                        </span>
                    </div>
                ) : (
                    isRunning && (
                        // No step detail yet (connecting, or a polling-mode run where step
                        // notifications are stream-borne): an indeterminate strip keeps the card
                        // visibly alive instead of looking stalled.
                        <div
                            className="h-1 rounded-full bg-fill-highlight-100 overflow-hidden"
                            aria-label="Setup in progress"
                        >
                            <div className="h-full w-1/3 rounded-full bg-accent animate-pulse" />
                        </div>
                    )
                )}
            </button>

            <div className="flex items-center justify-between gap-2 px-3.5 py-2 border-t border-primary">
                <ModeChip mode={mode} />
                <div className="flex items-center gap-1">
                    {progress.prUrl && (
                        <LemonButton
                            size="xsmall"
                            // The PR is the run's payoff: promote it once the run has finished.
                            type={progress.phase === 'completed' ? 'primary' : 'secondary'}
                            to={progress.prUrl}
                            targetBlank
                            icon={<IconPullRequest />}
                            onClick={(e) => e.stopPropagation()}
                        >
                            Review PR
                        </LemonButton>
                    )}
                    <LemonButton
                        size="xsmall"
                        icon={<IconExpand45 />}
                        onClick={onExpand}
                        tooltip="See all the details"
                        aria-label="Expand"
                    />
                    {onDismiss && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={onDismiss}
                            tooltip="Dismiss"
                            aria-label="Dismiss"
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
