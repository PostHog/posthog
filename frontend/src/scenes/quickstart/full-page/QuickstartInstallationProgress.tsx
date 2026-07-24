import { useActions } from 'kea'

import { IconCheckCircle, IconPullRequest, IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'
import { currentTaskLabel, pipClass, stepCounts, syncHeadline } from 'scenes/onboarding/shared/wizard-sync/helpers'
import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

// The chip's leading glyph: the page signals live activity with pulsing dots (not spinners),
// so working phases reuse that idiom and terminal phases get a small static icon.
function InstallationStatusDot({ progress }: { progress: InstallationProgress }): JSX.Element {
    if (progress.phase === 'completed') {
        return <IconCheckCircle className="text-sm text-success shrink-0" />
    }
    if (progress.phase === 'error') {
        return <IconWarning className="text-sm text-danger shrink-0" />
    }
    if (progress.prMerged) {
        return <IconPullRequest className="text-sm text-purple shrink-0" />
    }
    return (
        <span className="relative flex items-center justify-center size-2 shrink-0" aria-hidden="true">
            <span className="absolute size-2 rounded-full bg-accent opacity-25 animate-pulse" />
            <span className="relative size-1.5 rounded-full bg-accent" />
        </span>
    )
}

/**
 * Wizard progress as a one-line status chip next to the project token, height-matched so the
 * two read as one quiet family. The whole chip opens the detailed dialog.
 */
export function QuickstartInstallationProgress({ progress }: { progress: InstallationProgress }): JSX.Element {
    const { openDialog } = useActions(wizardSyncUiLogic)
    const task = currentTaskLabel(progress)
    const { completed, total } = stepCounts(progress.steps)

    return (
        <div className="min-w-0" role="status" aria-live="polite" data-attr="quickstart-installation-progress">
            <button
                type="button"
                onClick={openDialog}
                className="group flex w-fit max-w-full min-w-0 cursor-pointer items-center gap-2 rounded border bg-bg-light px-3 py-2 transition-colors hover:bg-fill-highlight-50"
                data-attr="quickstart-installation-status"
            >
                <InstallationStatusDot progress={progress} />
                <span className="text-xs font-medium text-secondary whitespace-nowrap">{syncHeadline(progress)}</span>
                {task && (
                    <span className="min-w-0 max-w-72 truncate text-xs text-tertiary" title={task}>
                        {task}
                    </span>
                )}
                {total > 0 && (
                    <span className="flex shrink-0 items-center gap-2">
                        <span className="flex w-16 items-center gap-0.5">
                            {progress.steps.map((step) => (
                                <span key={step.id} className={cn('h-1 flex-1 rounded-full', pipClass(step.status))} />
                            ))}
                        </span>
                        <span className="text-xs text-tertiary tabular-nums">
                            {completed}/{total}
                        </span>
                    </span>
                )}
                <span className="shrink-0 border-l pl-2 text-xs whitespace-nowrap text-tertiary group-hover:text-primary">
                    View details
                </span>
            </button>
        </div>
    )
}
