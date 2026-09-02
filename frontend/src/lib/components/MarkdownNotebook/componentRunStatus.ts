import { createContext, useContext } from 'react'

import { NotebookComponentBlockNode } from './types'

/** Run state of a component block, shown as the colour of the block's left gutter. */
export type NotebookComponentRunStatus = 'idle' | 'success' | 'error' | 'stale'

/** Supplied by the notebook host: this component knows how to colour a block, not how to run one.
 * Blocks with no resolver (and hosts with none) stay 'idle'. */
export type NotebookComponentRunStatusResolver = (node: NotebookComponentBlockNode) => NotebookComponentRunStatus

export const NotebookComponentRunStatusContext = createContext<NotebookComponentRunStatusResolver | null>(null)

export function useNotebookComponentRunStatus(node: NotebookComponentBlockNode): NotebookComponentRunStatus {
    const resolveRunStatus = useContext(NotebookComponentRunStatusContext)

    return resolveRunStatus?.(node) ?? 'idle'
}
