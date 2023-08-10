import {
    kea,
    props,
    key,
    path,
    BuiltLogic,
    selectors,
    actions,
    listeners,
    reducers,
    defaults,
    afterMount,
    beforeUnmount,
} from 'kea'
import type { notebookNodeLogicType } from './notebookNodeLogicType'
import { createContext, useContext } from 'react'
import { notebookLogicType } from '../Notebook/notebookLogicType'
import { JSONContent, Node } from '../Notebook/utils'
import { NotebookNodeType } from '~/types'
import posthog from 'posthog-js'

export type NotebookNodeLogicProps = {
    node: Node
    nodeId: string
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos: () => number
    title: string
}

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ nodeId }) => nodeId),
    actions({
        setExpanded: (expanded: boolean) => ({ expanded }),
        setTitle: (title: string) => ({ title }),
        insertAfter: (content: JSONContent) => ({ content }),
        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent) => ({ content, nodeType }),
        deleteNode: true,
        // TODO: Implement this
        // insertAfterNextEmptyLine: (content: JSONContent) => ({ content, nodeType }),
    }),

    defaults(() => (_, props) => ({
        title: props.title,
    })),

    reducers({
        expanded: [
            false,
            {
                setExpanded: (_, { expanded }) => expanded,
            },
        ],
        title: [
            '',
            {
                setTitle: (_, { title }) => title,
            },
        ],
    }),

    selectors({
        notebookLogic: [() => [(_, props) => props], (props): BuiltLogic<notebookLogicType> => props.notebookLogic],
    }),

    listeners(({ values, props }) => ({
        insertAfter: ({ content }) => {
            const logic = values.notebookLogic
            logic.values.editor?.insertContentAfterNode(props.getPos(), content)
        },

        deleteNode: () => {
            const logic = values.notebookLogic
            logic.values.editor?.deleteRange({ from: props.getPos(), to: props.getPos() + props.node.nodeSize }).run()
        },

        insertAfterLastNodeOfType: ({ nodeType, content }) => {
            const insertionPosition = props.getPos()
            const logic = values.notebookLogic
            logic.actions.insertAfterLastNodeOfType(nodeType, content, insertionPosition)
        },

        setExpanded: ({ expanded }) => {
            if (expanded) {
                posthog.capture('notebook node selected', {
                    node_type: props.nodeType,
                    short_id: props.notebookLogic.props.shortId,
                })
            }
        },
    })),

    afterMount((logic) => {
        logic.props.notebookLogic.actions.registerNodeLogic(logic)
    }),

    beforeUnmount((logic) => {
        logic.props.notebookLogic.actions.unregisterNodeLogic(logic)
    }),
])

export const NotebookNodeContext = createContext<BuiltLogic<notebookNodeLogicType> | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const useNotebookNode = (): BuiltLogic<notebookNodeLogicType> | undefined => {
    return useContext(NotebookNodeContext)
}
