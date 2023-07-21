import { kea, props, key, path, BuiltLogic, selectors, actions, listeners } from 'kea'
import type { notebookNodeLogicType } from './notebookNodeLogicType'
import { createContext, useContext } from 'react'
import { notebookLogicType } from '../Notebook/notebookLogicType'
import { JSONContent } from '../Notebook/utils'

export type NotebookNodeLogicProps = {
    nodeId: string
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos: () => number
}

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ nodeId }) => nodeId),
    selectors({
        notebookLogic: [() => [(_, props) => props], (props): BuiltLogic<notebookLogicType> => props.notebookLogic],
    }),

    actions({
        insertAfter: (content: JSONContent) => ({ content }),
        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent) => ({ content, nodeType }),
        // TODO: Implement this
        // insertAfterNextEmptyLine: (content: JSONContent) => ({ content, nodeType }),
    }),

    listeners(({ values, props }) => ({
        insertAfter: ({ content }) => {
            const logic = values.notebookLogic
            logic.values.editor?.insertContentAfterNode(props.getPos(), content)
        },

        insertAfterLastNodeOfType: ({ content, nodeType }) => {
            const logic = values.notebookLogic

            let insertionPosition = props.getPos()
            let nextNode = logic?.values.editor?.nextNode(insertionPosition)

            while (nextNode && logic.values.editor?.hasChildOfType(nextNode.node, nodeType)) {
                insertionPosition = nextNode.position
                nextNode = logic?.values.editor?.nextNode(insertionPosition)
            }

            logic.values.editor?.insertContentAfterNode(insertionPosition, content)
        },
    })),
])

export const NotebookNodeContext = createContext<BuiltLogic<notebookNodeLogicType> | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const useNotebookNode = (): BuiltLogic<notebookNodeLogicType> | undefined => {
    return useContext(NotebookNodeContext)
}
