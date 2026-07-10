import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    NotebookDependencyGraph,
    buildNotebookDependencyGraph,
    collectDependencyNodeIds,
} from '../Nodes/notebookNodeContent'
import { NotebookNodeType } from '../types'
import type { notebookNodeStalenessLogicType } from './notebookNodeStalenessLogicType'

export type NotebookNodeRunTerminalStatus = 'done' | 'failed' | 'interrupted'

export interface NotebookNodeStalenessLogicProps {
    shortId: string
}

const V2_NODE_TYPES: string[] = [NotebookNodeType.SQLV2, NotebookNodeType.PythonV2]

const staleDownstreamNodeIds = (graph: NotebookDependencyGraph, nodeId: string): string[] => {
    const downstream = collectDependencyNodeIds(graph, nodeId, 'downstream')
    downstream.delete(nodeId)
    // Only V2 cells participate: legacy cells have their own freshness system, and the
    // chain runner only knows how to dispatch V2 runs.
    return graph.nodes
        .filter((node) => downstream.has(node.nodeId) && V2_NODE_TYPES.includes(node.nodeType))
        .map((node) => node.nodeId)
}

/**
 * Journey 10: UI-only staleness for revamped (SQLV2/PythonV2) cells, plus the chain runner.
 *
 * When a cell's run lands, every transitive dependent is marked stale (its result now derives
 * from outdated data). "Run stale cells" re-runs the stale set in document order — which IS
 * dependency order, because a cell can only reference exports of earlier cells. Runs go
 * through each cell's own notebookNodeSQLV2Logic (the node logics listen for
 * `dispatchChainRun`), so operation serialization, polling, and interrupt all apply per link.
 * Flags are session-local by design (walkthrough decision: UI-only, no backend call).
 */
export const notebookNodeStalenessLogic = kea<notebookNodeStalenessLogicType>([
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookNodeStalenessLogic', key]),
    props({} as NotebookNodeStalenessLogicProps),
    key((props) => props.shortId),
    actions({
        // Reported by every V2 node logic from each of its run's terminal paths, whether the
        // run was user-clicked or chain-dispatched. `content` rides along on success so the
        // downstream set is computed against the document as it was when the result landed.
        nodeRunFinished: (nodeId: string, status: NotebookNodeRunTerminalStatus, content: JSONContent | null) => ({
            nodeId,
            status,
            content,
        }),
        markStaleNodeIds: (nodeIds: string[]) => ({ nodeIds }),
        clearNodeStale: (nodeId: string) => ({ nodeId }),
        runStaleChain: (content: JSONContent | null) => ({ content }),
        // Consumed by the matching notebookNodeSQLV2Logic, which builds refs and runs itself.
        dispatchChainRun: (nodeId: string) => ({ nodeId }),
        setChainQueue: (nodeIds: string[]) => ({ nodeIds }),
        shiftChain: true,
        abortChain: (reason: string | null) => ({ reason }),
    }),
    reducers({
        staleNodeIds: [
            {} as Record<string, true>,
            {
                markStaleNodeIds: (state, { nodeIds }) => {
                    if (!nodeIds.length) {
                        return state
                    }
                    const next = { ...state }
                    nodeIds.forEach((nodeId) => {
                        next[nodeId] = true
                    })
                    return next
                },
                clearNodeStale: (state, { nodeId }) => {
                    if (!(nodeId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[nodeId]
                    return next
                },
            },
        ],
        // Stale cells still to run; the head is the one currently running.
        chainQueue: [
            [] as string[],
            {
                setChainQueue: (_, { nodeIds }) => nodeIds,
                shiftChain: (state) => state.slice(1),
                abortChain: () => [],
            },
        ],
    }),
    selectors({
        staleCount: [(s) => [s.staleNodeIds], (staleNodeIds): number => Object.keys(staleNodeIds).length],
        isChainRunning: [(s) => [s.chainQueue], (chainQueue): boolean => chainQueue.length > 0],
    }),
    listeners(({ actions, values }) => ({
        nodeRunFinished: ({ nodeId, status, content }) => {
            if (status === 'done') {
                actions.clearNodeStale(nodeId)
                if (content) {
                    actions.markStaleNodeIds(staleDownstreamNodeIds(buildNotebookDependencyGraph(content), nodeId))
                }
            }

            if (values.chainQueue[0] !== nodeId) {
                return
            }
            if (status !== 'done') {
                actions.abortChain(nodeId)
                return
            }
            actions.shiftChain()
            // A queued cell can vanish before its turn (deleted mid-chain); skip what's gone
            // rather than dispatching a run nobody will pick up.
            if (content) {
                const graph = buildNotebookDependencyGraph(content)
                while (values.chainQueue.length > 0 && !graph.nodesById[values.chainQueue[0]]) {
                    actions.shiftChain()
                }
            }
            const next = values.chainQueue[0]
            if (next) {
                actions.dispatchChainRun(next)
            } else {
                lemonToast.success('Stale cells re-run.')
            }
        },
        runStaleChain: ({ content }) => {
            if (values.isChainRunning) {
                lemonToast.info('Stale cells are already being re-run.')
                return
            }
            if (!content) {
                return
            }
            const graph = buildNotebookDependencyGraph(content)
            // Document order is dependency order: a cell only references earlier exports.
            const queue = graph.nodes
                .filter((node) => V2_NODE_TYPES.includes(node.nodeType) && values.staleNodeIds[node.nodeId])
                .map((node) => node.nodeId)
            if (!queue.length) {
                lemonToast.info('No stale cells to run.')
                return
            }
            actions.setChainQueue(queue)
            actions.dispatchChainRun(queue[0])
        },
        abortChain: ({ reason }) => {
            if (reason) {
                lemonToast.warning('Stopped re-running stale cells: a cell did not finish successfully.')
            }
        },
    })),
])
