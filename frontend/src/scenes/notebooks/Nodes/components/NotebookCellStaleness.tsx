import { useComponentPanelState } from 'lib/components/MarkdownNotebook/componentPanelContext'

import type { NotebookStaleReason } from '../../Notebook/notebookNodeStalenessLogic'
import { NotebookRunDownstreamBanner } from './NotebookRunDownstreamBanner'
import { NotebookStaleCellBanner } from './NotebookStaleCellBanner'

export function NotebookCellStaleness({
    isStale,
    reason,
    downstreamCount,
    isChainRunning,
    onRun,
    disabledReason,
}: {
    isStale: boolean
    reason: NotebookStaleReason | null
    downstreamCount: number
    isChainRunning: boolean
    onRun: () => void
    disabledReason?: string
}): JSX.Element | null {
    const outputOnly = useComponentPanelState()?.outputOnly
    if (outputOnly || (!isStale && (downstreamCount === 0 || isChainRunning))) {
        return null
    }

    return (
        <div className="shrink-0 pb-2" onClick={(event) => event.stopPropagation()}>
            {isStale ? (
                <NotebookStaleCellBanner reason={reason ?? undefined} />
            ) : (
                <NotebookRunDownstreamBanner count={downstreamCount} onRun={onRun} disabledReason={disabledReason} />
            )}
        </div>
    )
}
