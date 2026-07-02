import { BuiltLogic } from 'kea'
import { createContext, useContext } from 'react'

import type { notebookNodeLogicType } from './notebookNodeLogicType'

export const NotebookNodeContext = createContext<BuiltLogic<notebookNodeLogicType> | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const useNotebookNode = (): BuiltLogic<notebookNodeLogicType> | undefined => {
    return useContext(NotebookNodeContext)
}

export const useRequiredNotebookNode = (): BuiltLogic<notebookNodeLogicType> => {
    const nodeLogic = useNotebookNode()
    if (!nodeLogic) {
        throw new Error('Notebook node context is required')
    }

    return nodeLogic
}
