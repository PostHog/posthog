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
    NotebookNodeAction,
    NotebookNodeAttributeProperties,
    NotebookNodeAttributes,
    NotebookNodeSettings,
} from '../Notebook/utils'
import { NotebookNodeResource, NotebookNodeType } from '~/types'
import posthog from 'posthog-js'
import { NotebookNodeMessages, NotebookNodeMessagesListeners } from './messaging/notebook-node-messages'

export type NotebookNodeLogicProps = {
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos?: () => number
    resizeable?: boolean | ((attributes: CustomNotebookNodeAttributes) => boolean)
    Settings?: NotebookNodeSettings
    messageListeners?: NotebookNodeMessagesListeners
    startExpanded?: boolean
    titlePlaceholder: string
} & NotebookNodeAttributeProperties<any>

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ attributes }) => attributes.nodeId || 'no-node-id-set'),
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
        insertOrSelectNextLine: true,
        setPreviousNode: (node: Node | null) => ({ node }),
        setNextNode: (node: Node | null) => ({ node }),
        deleteNode: true,
        selectNode: true,
        toggleEditing: (visible?: boolean) => ({ visible }),
        scrollIntoView: true,
        initializeNode: true,
        setMessageListeners: (listeners: NotebookNodeMessagesListeners) => ({ listeners }),
        setTitlePlaceholder: (titlePlaceholder: string) => ({ titlePlaceholder }),
    }),

    connect((props: NotebookNodeLogicProps) => ({
        actions: [props.notebookLogic, ['onUpdateEditor', 'setTextSelection']],
        values: [props.notebookLogic, ['editor', 'isEditable']],
    })),

    reducers(({ props }) => ({
        expanded: [
            props.startExpanded ?? true,
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
        nodeId: [(_, p) => [p.attributes], (nodeAttributes): string => nodeAttributes.nodeId],
        Settings: [() => [(_, props) => props], (props): NotebookNodeSettings | null => props.Settings ?? null],

        title: [
            (s) => [s.titlePlaceholder, s.nodeAttributes],
            (titlePlaceholder, nodeAttributes) => nodeAttributes.title || titlePlaceholder,
        ],
        // TODO: Fix the typing of nodeAttributes
        children: [(s) => [s.nodeAttributes], (nodeAttributes): NotebookNodeResource[] => nodeAttributes.children],

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
            if (!props.getPos) {
                return
            }
            const editor = values.notebookLogic.values.editor
            if (editor) {
                const { previous, next } = editor.getAdjacentNodes(props.getPos())
                actions.setPreviousNode(previous)
                actions.setNextNode(next)
            }
        },

        insertAfter: ({ content }) => {
            if (!props.getPos) {
                return
            }
            const logic = values.notebookLogic
            logic.values.editor?.insertContentAfterNode(props.getPos(), content)
        },

        deleteNode: () => {
            if (!props.getPos) {
                // TODO: somehow make this delete from the parent
                return
            }

            const logic = values.notebookLogic
            logic.values.editor?.deleteRange({ from: props.getPos(), to: props.getPos() + 1 }).run()
            if (values.notebookLogic.values.editingNodeId === values.nodeId) {
                values.notebookLogic.actions.setEditingNodeId(null)
            }
        },

        selectNode: () => {
            if (!props.getPos) {
                return
            }
            const editor = values.notebookLogic.values.editor

            if (editor) {
                editor.setSelection(props.getPos())
                editor.scrollToSelection()
            }
        },

        scrollIntoView: () => {
            if (!props.getPos) {
                return
            }
            values.editor?.scrollToPosition(props.getPos())
        },

        insertAfterLastNodeOfType: ({ nodeType, content }) => {
            if (!props.getPos) {
                return
            }
            const insertionPosition = props.getPos()
            values.notebookLogic.actions.insertAfterLastNodeOfType(nodeType, content, insertionPosition)
        },

        insertReplayCommentByTimestamp: ({ timestamp, sessionRecordingId }) => {
            if (!props.getPos) {
                return
            }
            const insertionPosition = props.getPos()
            values.notebookLogic.actions.insertReplayCommentByTimestamp({
                timestamp,
                sessionRecordingId,
                knownStartingPosition: insertionPosition,
                nodeId: values.nodeId,
            })
        },
        insertOrSelectNextLine: () => {
            if (!props.getPos || !values.isEditable) {
                return
            }

            if (!values.nextNode || !values.nextNode.isTextblock) {
                actions.insertAfter({
                    type: 'paragraph',
                })
            } else {
                actions.setTextSelection(props.getPos() + 1)
            }
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
        toggleEditing: ({ visible }) => {
            const shouldShowThis = typeof visible === 'boolean' ? visible : !values.notebookLogic.values.editingNodeId
            props.notebookLogic.actions.setEditingNodeId(shouldShowThis ? values.nodeId : null)
        },
        initializeNode: () => {
            const { __init } = values.nodeAttributes

            if (__init) {
                if (__init.expanded) {
                    actions.setExpanded(true)
                }
                if (__init.showSettings) {
                    actions.toggleEditing(true)
                }
                props.updateAttributes({ __init: null })
            }
        },
    })),

    afterMount((logic) => {
        const { props, actions, values } = logic
        props.notebookLogic.actions.registerNodeLogic(values.nodeId, logic as any)

        const isResizeable =
            typeof props.resizeable === 'function' ? props.resizeable(props.attributes) : props.resizeable ?? true

        actions.setResizeable(isResizeable)
        actions.initializeNode()
    }),

    beforeUnmount(({ props, values }) => {
        // Note this doesn't work as there may be other places where this is used. The NodeWrapper should be in charge of somehow unmounting this
        props.notebookLogic.actions.unregisterNodeLogic(values.nodeId)
    }),
])

export const NotebookNodeContext = createContext<BuiltLogic<notebookNodeLogicType> | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const useNotebookNode = (): BuiltLogic<notebookNodeLogicType> | undefined => {
    return useContext(NotebookNodeContext)
}
