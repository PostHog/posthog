import { IconCloud, IconDocument, IconExpand45, IconLaptop, IconPullRequest, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import {
    currentTaskLabel,
    elapsedLabel,
    formatElapsed,
    pendingQuestionLabel,
    prNameLabel,
    stepCounts,
    syncHeadline,
    toneTextClass,
    localModeLabel,
} from './helpers'
import { InstallationProgress } from './installationProgressLogic'
import { PipStrip } from './PipStrip'
import { StatusGlyph } from './StatusGlyph'

export type WizardSyncMode = 'cloud' | 'local'

// Tiny chip naming where the run is happening, so cloud and local runs read distinctly.
function ModeChip({ mode, startedByLabel }: { mode: WizardSyncMode; startedByLabel?: string | null }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1 text-xs text-muted">
            {mode === 'cloud' ? <IconCloud className="text-sm" /> : <IconLaptop className="text-sm" />}
            {mode === 'cloud' ? 'Cloud run' : localModeLabel(startedByLabel)}
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
    stale = false,
    onViewReport,
    onExpand,
    onDismiss,
    dismissTooltip = 'Dismiss',
    startedByLabel,
}: {
    progress: InstallationProgress
    elapsedSeconds: number
    mode: WizardSyncMode
    /** The run has gone quiet: the clock is replaced by the reason it stopped meaning anything. */
    stale?: boolean
    /** A teammate's name for a local run they started (null when it's the viewer's own run or unknown). */
    startedByLabel?: string | null
    /** Opens the run's handoff doc (the setup report) — the completed card's payoff for runs with
     * no PR. Only rendered when the progress actually carries a doc. */
    onViewReport?: () => void
    onExpand: () => void
    onDismiss?: () => void
    /** What the X actually does here — "Minimize" while the run is live, "Dismiss" once terminal. */
    dismissTooltip?: string
}): JSX.Element {
    const { completed, total } = stepCounts(progress.steps)
    const task = currentTaskLabel(progress)
    const question = pendingQuestionLabel(progress)
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
                        {question && (
                            // ph-no-capture: the prompt is whatever the wizard asked, so it can
                            // carry project detail that must not reach autocapture.
                            <p className="m-0 text-xs text-tertiary truncate ph-no-capture" title={question}>
                                {question}
                            </p>
                        )}
                    </div>
                    <span className="text-xs text-muted tabular-nums shrink-0" title={formatElapsed(elapsedSeconds)}>
                        {elapsedLabel(elapsedSeconds, stale)}
                    </span>
                </div>

                {total > 0 ? (
                    <div className="flex items-center gap-2">
                        <PipStrip steps={progress.steps} className="flex-1" />
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
                <ModeChip mode={mode} startedByLabel={startedByLabel} />
                <div className="flex items-center gap-1">
                    {progress.prUrl && (
                        // ph-no-capture: the label carries the customer's repo name and the href
                        // their PR url — neither may reach autocapture in shared app analytics.
                        // Truncated: owner + repo can reach ~140 chars and this footer sits inside
                        // a fixed 340px card next to the mode chip and two icon buttons.
                        <LemonButton
                            size="xsmall"
                            // The PR is the run's payoff: promote it once the run has finished.
                            type={progress.phase === 'completed' ? 'primary' : 'secondary'}
                            to={progress.prUrl}
                            targetBlank
                            icon={<IconPullRequest />}
                            onClick={(e) => e.stopPropagation()}
                            className="ph-no-capture"
                            tooltip={prNameLabel(progress.prUrl)}
                        >
                            <span className="truncate max-w-32">{prNameLabel(progress.prUrl)}</span>
                        </LemonButton>
                    )}
                    {progress.phase === 'completed' && !progress.prUrl && progress.handoffText && onViewReport && (
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            icon={<IconDocument />}
                            onClick={(e) => {
                                e.stopPropagation()
                                onViewReport()
                            }}
                            tooltip="What the agent set up, and what to check before you commit"
                            data-attr="wizard-sync-card-view-report"
                        >
                            Setup report
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
                            tooltip={dismissTooltip}
                            aria-label={dismissTooltip}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
