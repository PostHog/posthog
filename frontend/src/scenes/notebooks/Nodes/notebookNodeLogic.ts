import {
    BuiltLogic,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import { JSONContent, RichContentNode } from 'lib/components/RichContentEditor/types'

import { notebookLogicType } from '../Notebook/notebookLogicType'
import {
    CustomNotebookNodeAttributes,
    NotebookNodeAction,
    NotebookNodeAttributeProperties,
    NotebookNodeAttributes,
    NotebookNodeResource,
    NotebookNodeSettings,
    NotebookNodeType,
} from '../types'
import { NotebookNodeMessages, NotebookNodeMessagesListeners } from './messaging/notebook-node-messages'
import type { notebookNodeLogicType } from './notebookNodeLogicType'

export type NotebookNodeLogicProps = {
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos?: () => number | undefined
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
        insertOrSelectNextLine: true,
        setPreviousNode: (node: RichContentNode | null) => ({ node }),
        setNextNode: (node: RichContentNode | null) => ({ node }),
        deleteNode: true,
        selectNode: true,
        toggleEditing: (visible?: boolean) => ({ visible }),
        scrollIntoView: true,
        initializeNode: true,
        setMessageListeners: (listeners: NotebookNodeMessagesListeners) => ({ listeners }),
        setTitlePlaceholder: (titlePlaceholder: string) => ({ titlePlaceholder }),
        setRef: (ref: HTMLElement | null) => ({ ref }),
        toggleEditingTitle: (editing?: boolean) => ({ editing }),
        copyToClipboard: true,
        convertToBacklink: (href: string) => ({ href }),
    }),

    connect((props: NotebookNodeLogicProps) => ({
        actions: [props.notebookLogic, ['onUpdateEditor', 'setTextSelection']],
        values: [props.notebookLogic, ['editor', 'isEditable', 'comments']],
    })),

    reducers(({ props }) => ({
        ref: [
            null as HTMLElement | null,
            {
                setRef: (_, { ref }) => ref,
                unregisterNodeLogic: () => null,
            },
        ],
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
            null as RichContentNode | null,
            {
                setPreviousNode: (_, { node }) => node,
            },
        ],
        nextNode: [
            null as RichContentNode | null,
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
        isEditingTitle: [
            false,
            {
                toggleEditingTitle: (state, { editing }) => (typeof editing === 'boolean' ? editing : !state),
            },
        ],
    })),

    selectors({
        notebookLogic: [(_, p) => [p.notebookLogic], (notebookLogic) => notebookLogic],
        nodeAttributes: [(_, p) => [p.attributes], (nodeAttributes) => nodeAttributes],
        nodeId: [(_, p) => [p.attributes], (nodeAttributes): string => nodeAttributes.nodeId],
        nodeType: [(_, p) => [p.nodeType], (nodeType) => nodeType],
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

        sourceComment: [
            (s) => [s.comments, s.nodeId],
            (comments, nodeId) =>
                comments &&
                comments.find(
                    (comment) => comment.item_context?.type === 'node' && comment.item_context?.id === nodeId
                ),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        onUpdateEditor: async () => {
            if (!props.getPos) {
                return
            }
            const editor = values.notebookLogic.values.editor
            const pos = props.getPos()
            if (editor && pos) {
                const { previous, next } = editor.getAdjacentNodes(pos)
                actions.setPreviousNode(previous)
                actions.setNextNode(next)
            }
        },

        insertAfter: ({ content }) => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            const logic = values.notebookLogic
            logic.values.editor?.insertContentAfterNode(pos, content)
        },

        deleteNode: () => {
            const pos = props.getPos?.()
            if (!pos) {
                // TODO: somehow make this delete from the parent
                return
            }

            const logic = values.notebookLogic
            logic.values.editor?.deleteRange({ from: pos, to: pos + 1 }).run()
            if (values.notebookLogic.values.editingNodeId === values.nodeId) {
                values.notebookLogic.actions.setEditingNodeId(null)
            }
        },

        selectNode: () => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            const editor = values.notebookLogic.values.editor

            if (editor) {
                editor.setSelection(pos)
                editor.scrollToSelection()
            }
        },

        scrollIntoView: () => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            values.editor?.scrollToPosition(pos)
        },

        insertAfterLastNodeOfType: ({ nodeType, content }) => {
            const insertionPosition = props.getPos?.()
            if (!insertionPosition) {
                return
            }
            values.notebookLogic.actions.insertAfterLastNodeOfType(nodeType, content, insertionPosition)
        },
        insertOrSelectNextLine: () => {
            const pos = props.getPos?.()
            if (!pos || !values.isEditable) {
                return
            }

            if (!values.nextNode || !values.nextNode.isTextblock) {
                actions.insertAfter({
                    type: 'paragraph',
                })
            } else {
                actions.setTextSelection(pos + 1)
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
            const shouldShowThis =
                typeof visible === 'boolean' ? visible : values.notebookLogic.values.editingNodeId !== values.nodeId

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

        copyToClipboard: async () => {
            const { nodeAttributes } = values

            const htmlAttributesString = Object.entries(nodeAttributes)
                .map(([key, value]) => {
                    if (key === 'nodeId' || key.startsWith('__')) {
                        return ''
                    }

                    if (value === null || value === undefined) {
                        return ''
                    }

                    return `${key}='${JSON.stringify(value)}'`
                })
                .filter((x) => !!x)
                .join(' ')

            const html = `<${props.nodeType} ${htmlAttributesString} data-pm-slice="0 0 []"></${props.nodeType}>`

            const type = 'text/html'
            const blob = new Blob([html], { type })
            const data = [new ClipboardItem({ [type]: blob })]

            await window.navigator.clipboard.write(data)
        },
        convertToBacklink: ({ href }) => {
            const pos = props.getPos?.()
            const editor = values.notebookLogic.values.editor
            if (!pos || !editor) {
                return
            }

            editor.insertContentAfterNode(pos, {
                type: NotebookNodeType.Backlink,
                attrs: {
                    href,
                },
            })
            actions.deleteNode()
        },
    })),

    afterMount((logic) => {
        const { props, actions, values } = logic

        // The node logic is mounted after the editor is mounted, so we need to wait a tick before we can register it
        queueMicrotask(() => {
            props.notebookLogic.actions.registerNodeLogic(values.nodeId, logic as any)
        })

        const isResizeable =
            typeof props.resizeable === 'function' ? props.resizeable(props.attributes) : (props.resizeable ?? true)

        actions.setResizeable(isResizeable)
        actions.initializeNode()
    }),

    beforeUnmount(({ props, values }) => {
        // Note this doesn't work as there may be other places where this is used. The NodeWrapper should be in charge of somehow unmounting this
        props.notebookLogic.actions.unregisterNodeLogic(values.nodeId)
    }),
])
