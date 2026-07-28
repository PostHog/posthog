import { useValues } from 'kea'
import { useCallback } from 'react'

import type { NotebookComponentRunStatus, NotebookComponentRunStatusResolver } from 'lib/components/MarkdownNotebook'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'

import { NotebookNodeType } from '../types'
import { MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE } from './markdownNotebookRegistry'
import { NotebookNodeRunTerminalStatus, notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'

// Only the revamped code cells report run state. Every other block — markdown, insights, images —
// has nothing to run, so it stays grey.
const RUNNABLE_NODE_TYPES: (NotebookNodeType | undefined)[] = [NotebookNodeType.SQLV2, NotebookNodeType.PythonV2]

export function resolveNotebookComponentRunStatus(
    node: NotebookComponentBlockNode,
    staleNodeIds: Record<string, true>,
    nodeRunStatuses: Record<string, NotebookNodeRunTerminalStatus>
): NotebookComponentRunStatus {
    if (!RUNNABLE_NODE_TYPES.includes(MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[node.tagName])) {
        return 'idle'
    }

    // A cell pins its own id the first time it runs; until then the block id is a content
    // fingerprint, which is what the rest of the notebook keys the cell by too.
    const nodeId = typeof node.props.nodeId === 'string' ? node.props.nodeId : node.id
    const runStatus = nodeRunStatuses[nodeId]

    // A run that failed or was interrupted left no result behind, so there is nothing for a
    // later upstream run to make stale — the failure is the more useful signal.
    if (runStatus === 'failed' || runStatus === 'interrupted') {
        return 'error'
    }
    if (staleNodeIds[nodeId]) {
        return 'stale'
    }
    // Run outcomes are session-local, so on a reload the persisted result stands in for them.
    return runStatus === 'done' || node.props.result ? 'success' : 'idle'
}

export function useNotebookComponentRunStatusResolver(shortId: string): NotebookComponentRunStatusResolver {
    const { staleNodeIds, nodeRunStatuses } = useValues(notebookNodeStalenessLogic({ shortId }))

    return useCallback(
        (node: NotebookComponentBlockNode) => resolveNotebookComponentRunStatus(node, staleNodeIds, nodeRunStatuses),
        [staleNodeIds, nodeRunStatuses]
    )
}
