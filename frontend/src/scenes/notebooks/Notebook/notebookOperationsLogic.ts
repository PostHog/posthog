import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import type { notebookOperationsLogicType } from './notebookOperationsLogicType'

export interface NotebookOperationsLogicProps {
    shortId: string
}

export type NotebookOperation = {
    /** Unique per operation, e.g. `${nodeId}:run` — re-registering the same id is idempotent. */
    id: string
    nodeId: string
    kind: 'run' | 'page'
}

/**
 * Notebook-wide registry of in-flight data operations (query runs, page fetches).
 *
 * One operation at a time per notebook: node logics register on start and release on every
 * terminal path, and gate their own actions on `isBusy` so a user can't stack operations
 * across cells. Client-local UX only — collaborators and other tabs are not serialized;
 * server-side guards remain the real enforcement.
 */
export const notebookOperationsLogic = kea<notebookOperationsLogicType>([
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookOperationsLogic', key]),
    props({} as NotebookOperationsLogicProps),
    key((props) => props.shortId),
    actions({
        startOperation: (operation: NotebookOperation) => ({ operation }),
        finishOperation: (id: string) => ({ id }),
        // Sweep for unmount/delete of a node: a removed cell must never wedge the notebook.
        finishNodeOperations: (nodeId: string) => ({ nodeId }),
    }),
    reducers({
        operations: [
            {} as Record<string, NotebookOperation>,
            {
                startOperation: (state, { operation }) => ({ ...state, [operation.id]: operation }),
                finishOperation: (state, { id }) => {
                    if (!(id in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[id]
                    return next
                },
                finishNodeOperations: (state, { nodeId }) =>
                    Object.fromEntries(Object.entries(state).filter(([, operation]) => operation.nodeId !== nodeId)),
            },
        ],
    }),
    selectors({
        activeOperation: [
            (s) => [s.operations],
            (operations: Record<string, NotebookOperation>): NotebookOperation | null =>
                Object.values(operations)[0] ?? null,
        ],
        isBusy: [(s) => [s.operations], (operations): boolean => Object.keys(operations).length > 0],
        // Journey 14: runs dispatch concurrently (the backend and sandbox order execution),
        // so only an in-flight page fetch — which holds a web worker — still gates new runs.
        activePageOperation: [
            (s) => [s.operations],
            (operations: Record<string, NotebookOperation>): NotebookOperation | null =>
                Object.values(operations).find((operation) => operation.kind === 'page') ?? null,
        ],
    }),
])
