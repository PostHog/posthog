import { useValues } from 'kea'
import { useCallback } from 'react'

import type { NotebookComponentRunStatus, NotebookComponentRunStatusResolver } from 'lib/components/MarkdownNotebook'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'

import { NotebookNodeType } from '../types'
import { MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE } from './markdownNotebookRegistry'
import {
    NotebookNodeRunTerminalStatus,
    notebookNodeStalenessLogic,
    NotebookStaleReason,
} from './notebookNodeStalenessLogic'

// Only the revamped code cells report run state. Every other block — markdown, insights, images —
// has nothing to run, so it stays grey.
const RUNNABLE_NODE_TYPES: (NotebookNodeType | undefined)[] = [NotebookNodeType.SQLV2, NotebookNodeType.PythonV2]

const TERMINAL_STATUSES: NotebookNodeRunTerminalStatus[] = ['done', 'failed', 'interrupted']

const persistedRunStatus = (value: unknown): NotebookNodeRunTerminalStatus | undefined =>
    TERMINAL_STATUSES.find((status) => status === value)

export function resolveNotebookComponentRunStatus(
    node: NotebookComponentBlockNode,
    staleNodeIds: Record<string, NotebookStaleReason>,
    nodeRunStatuses: Record<string, NotebookNodeRunTerminalStatus>
): NotebookComponentRunStatus {
    if (!RUNNABLE_NODE_TYPES.includes(MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[node.tagName])) {
        return 'idle'
    }

    // A cell pins its own id the first time it runs; until then the block id is a content
    // fingerprint, which is what the rest of the notebook keys the cell by too.
    const nodeId = typeof node.props.nodeId === 'string' ? node.props.nodeId : node.id
    // The session's own record of the run wins. A cell that produced a result persists how that
    // run ended too, so a reload keeps the color — an interrupted run leaves a partial result
    // behind just like a completed one, so the result alone can't stand in for the outcome.
    const runStatus = nodeRunStatuses[nodeId] ?? persistedRunStatus(node.props.runStatus)

    // A cell that didn't finish has nothing trustworthy to be out of date, so its own outcome
    // outranks an upstream re-run.
    if (runStatus === 'failed' || runStatus === 'interrupted') {
        return 'error'
    }
    if (staleNodeIds[nodeId]) {
        return 'stale'
    }
    return runStatus === 'done' ? 'success' : 'idle'
}

export function useNotebookComponentRunStatusResolver(shortId: string): NotebookComponentRunStatusResolver {
    const { staleNodeIds, nodeRunStatuses } = useValues(notebookNodeStalenessLogic({ shortId }))

    return useCallback(
        (node: NotebookComponentBlockNode) => resolveNotebookComponentRunStatus(node, staleNodeIds, nodeRunStatuses),
        [staleNodeIds, nodeRunStatuses]
    )
}
