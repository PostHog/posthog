import {
    actions,
    afterMount,
    beforeUnmount,
    BuiltLogic,
    connect,
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
import {
    CustomNotebookNodeAttributes,
    JSONContent,
    Node,
    NotebookNode,
    NotebookNodeAttributeProperties,
    NotebookNodeAttributes,
    NotebookNodeWidget,
} from '../Notebook/utils'
import { NotebookNodeType } from '~/types'
import posthog from 'posthog-js'

export type NotebookNodeLogicProps = {
    node: NotebookNode
    nodeId: string
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos: () => number
    title: string | ((attributes: CustomNotebookNodeAttributes) => Promise<string>)
    resizeable: boolean | ((attributes: CustomNotebookNodeAttributes) => boolean)
    widgets: NotebookNodeWidget[]
    startExpanded: boolean
} & NotebookNodeAttributeProperties<any>

async function renderTitle(
    title: NotebookNodeLogicProps['title'],
    attrs: NotebookNodeLogicProps['attributes']
): Promise<string> {
    if (typeof attrs.title === 'string' && attrs.title.length > 0) {
        return attrs.title
    }

    return title instanceof Function ? await title(attrs) : title
}

const computeResizeable = (
    resizeable: NotebookNodeLogicProps['resizeable'],
    attrs: NotebookNodeLogicProps['attributes']
): boolean => (typeof resizeable === 'function' ? resizeable(attrs) : resizeable)

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
        updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => ({ attributes }),
        insertReplayCommentByTimestamp: (timestamp: number, sessionRecordingId: string) => ({
            timestamp,
            sessionRecordingId,
        }),
        setWidgetsVisible: (visible: boolean) => ({ visible }),
        setPreviousNode: (node: Node | null) => ({ node }),
        setNextNode: (node: Node | null) => ({ node }),
        deleteNode: true,
    }),

    connect((props: NotebookNodeLogicProps) => ({
        actions: [props.notebookLogic, ['onUpdateEditor']],
        values: [props.notebookLogic, ['editor']],
    })),

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
        previousNode: [
            null as Node | null,
            {
                setPreviousNode: (_, { node }) => node,
            },
        ],
        nextNode: [
            null as Node | null,
            {
                setNextNode: (_, { node }) => node,
            },
        ],
        widgetsVisible: [
            false,
            {
                setWidgetsVisible: (_, { visible }) => visible,
            },
        ],
    })),

    selectors({
        notebookLogic: [(_, p) => [p.notebookLogic], (notebookLogic) => notebookLogic],
        nodeAttributes: [(_, p) => [p.attributes], (nodeAttributes) => nodeAttributes],
        widgets: [(_, p) => [p.widgets], (widgets) => widgets],
        isShowingWidgets: [
            (s, p) => [s.widgetsVisible, p.widgets],
            (widgetsVisible, widgets) => !!widgets.length && widgetsVisible,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        onUpdateEditor: async () => {
            const editor = values.notebookLogic.values.editor
            if (editor) {
                const pos = props.getPos()
                const { previous, next } = editor.getAdjacentNodes(pos)
                actions.setPreviousNode(previous)
                actions.setNextNode(next)
            }
        },

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
        const renderedTitle = await renderTitle(logic.props.title, logic.props.attributes)
        logic.actions.setTitle(renderedTitle)
        const resizeable = computeResizeable(logic.props.resizeable, logic.props.attributes)
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
