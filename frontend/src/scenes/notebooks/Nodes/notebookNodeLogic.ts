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
    NotebookNodeAction,
    NotebookNodeAttributeProperties,
    NotebookNodeAttributes,
    NotebookNodeSettings,
} from '../Notebook/utils'
import { NotebookNodeType } from '~/types'
import posthog from 'posthog-js'
import { NotebookNodeMessages, NotebookNodeMessagesListeners } from './messaging/notebook-node-messages'

export type NotebookNodeLogicProps = {
    node: NotebookNode
    nodeId: string
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos: () => number
    resizeable: boolean | ((attributes: CustomNotebookNodeAttributes) => boolean)
    settings: NotebookNodeSettings
    messageListeners?: NotebookNodeMessagesListeners
    startExpanded: boolean
    titlePlaceholder: string
} & NotebookNodeAttributeProperties<any>

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
        setResizeable: (resizeable: boolean) => ({ resizeable }),
        setActions: (actions: (NotebookNodeAction | undefined)[]) => ({ actions }),
        insertAfter: (content: JSONContent) => ({ content }),
        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent) => ({ content, nodeType }),
        updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => ({ attributes }),
        insertReplayCommentByTimestamp: (timestamp: number, sessionRecordingId: string) => ({
            timestamp,
            sessionRecordingId,
        }),
        setPreviousNode: (node: Node | null) => ({ node }),
        setNextNode: (node: Node | null) => ({ node }),
        deleteNode: true,
        selectNode: true,
        toggleEditing: true,
        scrollIntoView: true,
        initializeNode: true,
        setMessageListeners: (listeners: NotebookNodeMessagesListeners) => ({ listeners }),
        setTitlePlaceholder: (titlePlaceholder: string) => ({ titlePlaceholder }),
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
        actions: [
            [] as NotebookNodeAction[],
            {
                setActions: (_, { actions }) => actions.filter((x) => !!x) as NotebookNodeAction[],
            },
        ],
        messageListeners: [
            props.messageListeners as NotebookNodeMessagesListeners,
            {
                setMessageListeners: (_, { listeners }) => listeners,
            },
        ],

        titlePlaceholder: [
            props.titlePlaceholder,
            {
                setTitlePlaceholder: (_, { titlePlaceholder }) => titlePlaceholder,
            },
        ],
    })),

    selectors({
        notebookLogic: [(_, p) => [p.notebookLogic], (notebookLogic) => notebookLogic],
        nodeAttributes: [(_, p) => [p.attributes], (nodeAttributes) => nodeAttributes],
        settings: [(_, p) => [p.settings], (settings) => settings],
        title: [
            (s) => [s.titlePlaceholder, s.nodeAttributes],
            (titlePlaceholder, nodeAttributes) => nodeAttributes.title || titlePlaceholder,
        ],

        sendMessage: [
            (s) => [s.messageListeners],
            (messageListeners) => {
                return <T extends keyof NotebookNodeMessages>(
                    message: T,
                    payload: NotebookNodeMessages[T]
                ): boolean => {
                    if (!messageListeners[message]) {
                        return false
                    }

                    messageListeners[message]?.(payload)
                    return true
                }
            },
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
            if (values.notebookLogic.values.editingNodeId === props.nodeId) {
                values.notebookLogic.actions.setEditingNodeId(null)
            }
        },

        selectNode: () => {
            const editor = values.notebookLogic.values.editor

            if (editor) {
                editor.setSelection(props.getPos())
                editor.scrollToSelection()
            }
        },

        scrollIntoView: () => {
            values.editor?.scrollToPosition(props.getPos())
        },

        insertAfterLastNodeOfType: ({ nodeType, content }) => {
            const insertionPosition = props.getPos()
            values.notebookLogic.actions.insertAfterLastNodeOfType(nodeType, content, insertionPosition)
        },

        insertReplayCommentByTimestamp: ({ timestamp, sessionRecordingId }) => {
            const insertionPosition = props.getPos()
            values.notebookLogic.actions.insertReplayCommentByTimestamp({
                timestamp,
                sessionRecordingId,
                knownStartingPosition: insertionPosition,
                nodeId: props.nodeId,
            })
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
        toggleEditing: () => {
            props.notebookLogic.actions.setEditingNodeId(
                props.notebookLogic.values.editingNodeId === props.nodeId ? null : props.nodeId
            )
        },
        initializeNode: () => {
            const { __init } = values.nodeAttributes

            if (__init) {
                if (__init.expanded) {
                    actions.setExpanded(true)
                }
                if (__init.showSettings) {
                    actions.toggleEditing()
                }
                props.updateAttributes({ __init: null })
            }
        },
    })),

    afterMount(async (logic) => {
        logic.props.notebookLogic.actions.registerNodeLogic(logic as any)
        const resizeable = computeResizeable(logic.props.resizeable, logic.props.attributes)
        logic.actions.setResizeable(resizeable)
        logic.actions.initializeNode()
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
