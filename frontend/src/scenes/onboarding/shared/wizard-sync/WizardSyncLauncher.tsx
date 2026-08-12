import { cn } from 'lib/utils/css-classes'

import { elapsedLabel } from './helpers'
import { InstallationProgress } from './installationProgressLogic'
import { StatusGlyph } from './StatusGlyph'

// The minimized state: a small pill that restores the card. This is the "activate it back" affordance.
export function WizardSyncLauncher({
    progress,
    elapsedSeconds,
    stale = false,
    onRestore,
}: {
    progress: InstallationProgress
    elapsedSeconds: number
    stale?: boolean
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
            <span className="text-xs text-muted tabular-nums">{elapsedLabel(elapsedSeconds, stale)}</span>
        </button>
    )
}
