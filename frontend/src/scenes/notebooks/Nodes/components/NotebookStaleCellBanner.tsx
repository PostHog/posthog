import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

// Journey 10: shown on a V2 cell whose upstream ran after it. The action re-runs every stale
// V2 cell in the notebook in document order (= dependency order), via the staleness logic.
export function NotebookStaleCellBanner({
    staleCount,
    onRun,
    disabledReason,
}: {
    staleCount: number
    onRun: () => void
    disabledReason?: string
}): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            className="mx-2 mt-1 p-2 text-xs"
            action={{
                children: staleCount > 1 ? `Run stale cells (${staleCount})` : 'Run stale cell',
                onClick: onRun,
                disabledReason,
                size: 'xsmall',
            }}
        >
            Stale: an upstream cell ran after this one.
        </LemonBanner>
    )
}
