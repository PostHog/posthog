import {
    actions,
    afterMount,
    beforeUnmount,
    BuiltLogic,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import type { notebookNodeLogicType } from './notebookNodeLogicType'
import { createContext, useContext } from 'react'
import { notebookLogicType } from '../Notebook/notebookLogicType'
import { CustomNotebookNodeAttributes, JSONContent, Node, NotebookNodeWidget } from '../Notebook/utils'
import { NotebookNodeType } from '~/types'
import posthog from 'posthog-js'

export type NotebookNodeLogicProps = {
    node: Node
    nodeId: string
    nodeType: NotebookNodeType
    nodeAttributes: CustomNotebookNodeAttributes
    updateAttributes: (attributes: CustomNotebookNodeAttributes) => void
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos: () => number
    title: string | ((attributes: any) => Promise<string>)
    resizeable: boolean | ((attributes: any) => Promise<boolean>)
    widgets: NotebookNodeWidget[]
    startExpanded: boolean
}

async function renderTitle(
    title: NotebookNodeLogicProps['title'],
    attrs: NotebookNodeLogicProps['nodeAttributes']
): Promise<string> {
    if (typeof attrs.title === 'string' && attrs.title.length > 0) {
        return attrs.title
    }

    return typeof title === 'function' ? await title(attrs) : title
}

async function renderResizeable(
    resizeable: NotebookNodeLogicProps['resizeable'],
    attrs: NotebookNodeLogicProps['nodeAttributes']
): Promise<boolean> {
    return typeof resizeable === 'function' ? await resizeable(attrs) : resizeable
}

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ nodeId }) => nodeId || 'no-node-id-set'),
    actions({
        setExpanded: (expanded: boolean) => ({ expanded }),
        setTitle: (title: string) => ({ title }),
        setResizeable: (resizeable: boolean) => ({ resizeable }),
        insertAfter: (content: JSONContent) => ({ content }),
        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent) => ({ content, nodeType }),
        updateAttributes: (attributes: CustomNotebookNodeAttributes) => ({ attributes }),
        insertReplayCommentByTimestamp: (timestamp: number, sessionRecordingId: string) => ({
            timestamp,
            sessionRecordingId,
        }),
        deleteNode: true,
        // TODO: Implement this
        // insertAfterNextEmptyLine: (content: JSONContent) => ({ content, nodeType }),
    }),

    reducers(({ props }) => ({
        expanded: [
            props.startExpanded,
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
        resizeable: [
            false,
            {
                setResizeable: (_, { resizeable }) => resizeable,
            },
        ],
    })),

    selectors({
        notebookLogic: [(_, p) => [p.notebookLogic], (notebookLogic) => notebookLogic],
        nodeAttributes: [(_, p) => [p.nodeAttributes], (nodeAttributes) => nodeAttributes],
        widgets: [(_, p) => [p.widgets], (widgets) => widgets],
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
            values.notebookLogic.actions.insertAfterLastNodeOfType(nodeType, content, insertionPosition)
        },

        insertReplayCommentByTimestamp: ({ timestamp, sessionRecordingId }) => {
            const insertionPosition = props.getPos()
            values.notebookLogic.actions.insertReplayCommentByTimestamp(
                timestamp,
                sessionRecordingId,
                insertionPosition
            )
        },

        setExpanded: ({ expanded }) => {
            if (expanded) {
                posthog.capture('notebook node expanded', {
                    node_type: props.nodeType,
                    short_id: props.notebookLogic.props.shortId,
                })
            }
        },

        updateAttributes: ({ attributes }) => {
            props.updateAttributes(attributes)
        },
    })),

    afterMount(async (logic) => {
        logic.props.notebookLogic.actions.registerNodeLogic(logic as any)
        const renderedTitle = await renderTitle(logic.props.title, logic.props.nodeAttributes)
        logic.actions.setTitle(renderedTitle)
        const resizeable = await renderResizeable(logic.props.resizeable, logic.props.nodeAttributes)
        logic.actions.setResizeable(resizeable)
        logic.actions.updateAttributes({ title: renderedTitle })
    }),

    beforeUnmount((logic) => {
        logic.props.notebookLogic.actions.unregisterNodeLogic(logic as any)
    }),
])

export const NotebookNodeContext = createContext<BuiltLogic<notebookNodeLogicType> | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const useNotebookNode = (): BuiltLogic<notebookNodeLogicType> | undefined => {
    return useContext(NotebookNodeContext)
}
