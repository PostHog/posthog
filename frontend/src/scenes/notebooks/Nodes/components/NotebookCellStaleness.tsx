import { BuiltLogic, useActions, useValues } from 'kea'

import { useComponentPanelState } from 'lib/components/MarkdownNotebook/componentPanelContext'

import type { notebookNodeSQLV2LogicType } from '../notebookNodeSQLV2LogicType'
import { NotebookRunDownstreamBanner } from './NotebookRunDownstreamBanner'
import { NotebookStaleCellBanner } from './NotebookStaleCellBanner'

export function NotebookCellStaleness({
    logic,
}: {
    logic: BuiltLogic<notebookNodeSQLV2LogicType>
}): JSX.Element | null {
    const { isStale, staleReason, staleDownstreamCount, isChainRunning, isRunning, operationBlockReason } =
        useValues(logic)
    const { runStaleChain } = useActions(logic)
    const outputOnly = useComponentPanelState()?.outputOnly
    if (outputOnly || (!isStale && (staleDownstreamCount === 0 || isChainRunning))) {
        return null
    }

    return (
        <div className="shrink-0 pb-2" onClick={(event) => event.stopPropagation()}>
            {isStale ? (
                <NotebookStaleCellBanner reason={staleReason ?? undefined} />
            ) : (
                <NotebookRunDownstreamBanner
                    count={staleDownstreamCount}
                    onRun={() => runStaleChain(logic.props.getContent?.() ?? null, logic.props.nodeId)}
                    disabledReason={isRunning ? 'This cell is running' : (operationBlockReason ?? undefined)}
                />
            )}
        </div>
    )
}
