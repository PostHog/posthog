import {
    actions,
    afterMount,
    beforeUnmount,
    BuiltLogic,
    defaults,
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
import { JSONContent, Node, NotebookNodeWidget } from '../Notebook/utils'
import { NotebookNodeType } from '~/types'
import posthog from 'posthog-js'

export type NotebookNodeLogicProps = {
    node: Node
    nodeId: string
    nodeType: NotebookNodeType
    nodeAttributes: Record<string, any>
    updateAttributes: (attributes: Record<string, any>) => void
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos: () => number
    title: string
    widgets: NotebookNodeWidget[]
    domNode: HTMLElement
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
        updateAttributes: (attributes: Record<string, any>) => ({ attributes }),
        setopenWidgetKeys: (widgetKeys: string[]) => ({ widgetKeys }),
        addActiveWidget: (key: string) => ({ key }),
        removeActiveWidget: (key: string) => ({ key }),
        insertReplayCommentByTimestamp: (timestamp: number, sessionRecordingId: string) => ({
            timestamp,
            sessionRecordingId,
        }),
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
        openWidgetKeys: [
            [] as string[],
            {
                setopenWidgetKeys: (_, { widgetKeys }) => widgetKeys,
            },
        ],
    }),

    selectors({
        domNode: [() => [(_, props) => props], (props): HTMLElement => props.domNode],
        notebookLogic: [() => [(_, props) => props], (props): BuiltLogic<notebookLogicType> => props.notebookLogic],
        nodeAttributes: [() => [(_, props) => props], (props): Record<string, any> => props.nodeAttributes],
        widgets: [() => [(_, props) => props], (props): NotebookNodeWidget[] => props.widgets],
        unopenWidgets: [
            (s) => [s.openWidgetKeys, (_, props) => props.widgets],
            (openWidgetKeys, widgets: NotebookNodeWidget[]) =>
                widgets.filter((widget) => !openWidgetKeys.includes(widget.key)),
        ],
        openWidgets: [
            (s) => [s.openWidgetKeys, (_, props) => props.widgets],
            (openWidgetKeys, widgets: NotebookNodeWidget[]) =>
                widgets.filter((widget) => openWidgetKeys.includes(widget.key)),
        ],
    }),

    listeners(({ values, actions, props }) => ({
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

        addActiveWidget: ({ key }) => {
            actions.setopenWidgetKeys(
                [...values.openWidgetKeys, key].filter((value, index, array) => array.indexOf(value) === index)
            )
        },
        removeActiveWidget: ({ key }) => {
            const index = values.openWidgetKeys.indexOf(key)
            const newopenWidgetKeys = [...values.openWidgetKeys]
            newopenWidgetKeys.splice(index, 1)
            actions.setopenWidgetKeys(newopenWidgetKeys)
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
