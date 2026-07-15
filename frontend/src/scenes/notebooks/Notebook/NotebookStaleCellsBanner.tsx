import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { notebookLogic } from './notebookLogic'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'
import { notebookOperationsLogic } from './notebookOperationsLogic'

// Journey 10: the single home of the "run stale cells" action. It lives at notebook level
// because the chain always runs the whole stale set (not "downstream of this cell"), so a
// per-cell button would imply a per-cell action that doesn't exist. Stale cells themselves
// only carry an identification warning (NotebookStaleCellBanner).
export function NotebookStaleCellsBanner(): JSX.Element | null {
    const logic = useMountedLogic(notebookLogic)
    const { content } = useValues(logic)
    const shortId = logic.props.shortId

    const stalenessLogic = notebookNodeStalenessLogic({ shortId })
    const { staleCount, isChainRunning } = useValues(stalenessLogic)
    const { runStaleChain } = useActions(stalenessLogic)
    const { isBusy } = useValues(notebookOperationsLogic({ shortId }))

    if (staleCount === 0) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            className="sticky top-0 z-20 mb-2 p-2"
            action={{
                children: staleCount === 1 ? 'Run stale cell' : `Run all stale cells (${staleCount})`,
                onClick: () => runStaleChain(content ?? null),
                loading: isChainRunning,
                disabledReason: isChainRunning
                    ? 'Stale cells are re-running'
                    : isBusy
                      ? 'Another operation is running in this notebook'
                      : undefined,
                size: 'small',
            }}
        >
            {staleCount === 1
                ? '1 cell is showing outdated results.'
                : `${staleCount} cells are showing outdated results.`}
        </LemonBanner>
    )
}
