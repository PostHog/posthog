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

import { LemonMenuItems } from '@posthog/lemon-ui'

import api from 'lib/api'
import { JSONContent, RichContentNode } from 'lib/components/RichContentEditor/types'
import { hashCodeForString } from 'lib/utils'

import { notebookLogicType } from '../Notebook/notebookLogicType'
import {
    CustomNotebookNodeAttributes,
    NotebookNodeAction,
    NotebookNodeAttributeProperties,
    NotebookNodeAttributes,
    NotebookNodeResource,
    NotebookNodeSettings,
    NotebookNodeSettingsPlacement,
    NotebookNodeType,
} from '../types'
import { NotebookNodeMessages, NotebookNodeMessagesListeners } from './messaging/notebook-node-messages'
import { VariableUsage } from './notebookNodeContent'
import type { notebookNodeLogicType } from './notebookNodeLogicType'
import {
    PythonExecutionResult,
    PythonExecutionVariable,
    PythonKernelExecuteResponse,
    buildPythonExecutionError,
    buildPythonExecutionResult,
} from './pythonExecution'

export type PythonRunMode = 'auto' | 'cell_upstream' | 'cell' | 'cell_downstream'

type RunPythonCellParams = {
    notebookId: string
    code: string
    exportedGlobals: { name: string; type: string }[]
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => void
    setPythonRunLoading: (loading: boolean) => void
}

const runPythonCell = async ({
    notebookId,
    code,
    exportedGlobals,
    updateAttributes,
    setPythonRunLoading,
}: RunPythonCellParams): Promise<boolean> => {
    setPythonRunLoading(true)
    try {
        const execution = (await api.notebooks.kernelExecute(notebookId, {
            code,
            return_variables: exportedGlobals.length > 0,
        })) as PythonKernelExecuteResponse

        updateAttributes({
            pythonExecution: buildPythonExecutionResult(execution, exportedGlobals),
            pythonExecutionCodeHash: hashCodeForString(code),
        })
        return true
    } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to run Python cell.'
        updateAttributes({
            pythonExecution: buildPythonExecutionError(message, exportedGlobals),
            pythonExecutionCodeHash: hashCodeForString(code),
        })
        return false
    } finally {
        setPythonRunLoading(false)
    }
}

export type NotebookNodeLogicProps = {
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos?: () => number | undefined
    resizeable?: boolean | ((attributes: CustomNotebookNodeAttributes) => boolean)
    Settings?: NotebookNodeSettings
    messageListeners?: NotebookNodeMessagesListeners
    startExpanded?: boolean
    titlePlaceholder: string
    settingsPlacement?: NotebookNodeSettingsPlacement
} & NotebookNodeAttributeProperties<any>

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ attributes }) => attributes.nodeId || 'no-node-id-set'),
    actions({
        setExpanded: (expanded: boolean) => ({ expanded }),
        setResizeable: (resizeable: boolean) => ({ resizeable }),
        setActions: (actions: (NotebookNodeAction | undefined)[]) => ({ actions }),
        setMenuItems: (menuItems: LemonMenuItems | null) => ({ menuItems }),
        insertAfter: (content: JSONContent) => ({ content }),
        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent) => ({ content, nodeType }),
        updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => ({ attributes }),
        insertOrSelectNextLine: true,
        setPreviousNode: (node: RichContentNode | null) => ({ node }),
        setNextNode: (node: RichContentNode | null) => ({ node }),
        deleteNode: true,
        selectNode: (scroll?: boolean) => ({ scroll }),
        toggleEditing: (visible?: boolean) => ({ visible }),
        scrollIntoView: true,
        initializeNode: true,
        setMessageListeners: (listeners: NotebookNodeMessagesListeners) => ({ listeners }),
        setTitlePlaceholder: (titlePlaceholder: string) => ({ titlePlaceholder }),
        setRef: (ref: HTMLElement | null) => ({ ref }),
        toggleEditingTitle: (editing?: boolean) => ({ editing }),
        copyToClipboard: true,
        convertToBacklink: (href: string) => ({ href }),
        navigateToNode: (nodeId: string) => ({ nodeId }),
        runPythonNode: (payload: { code: string }) => payload,
        runPythonNodeWithMode: (payload: { mode: PythonRunMode }) => payload,
        setPythonRunLoading: (loading: boolean) => ({ loading }),
        setPythonRunQueued: (queued: boolean) => ({ queued }),
    }),

    connect((props: NotebookNodeLogicProps) => ({
        actions: [props.notebookLogic, ['onUpdateEditor', 'setTextSelection']],
        values: [props.notebookLogic, ['editor', 'isEditable', 'comments', 'pythonNodeSummaries', 'notebook']],
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
        customMenuItems: [
            null as LemonMenuItems | null,
            {
                setMenuItems: (_, { menuItems }) => menuItems,
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
        pythonRunLoading: [
            false,
            {
                setPythonRunLoading: (_, { loading }) => loading,
            },
        ],
        pythonRunQueued: [
            false,
            {
                setPythonRunQueued: (_, { queued }) => queued,
            },
        ],
    })),

    selectors({
        notebookLogic: [(_, p) => [p.notebookLogic], (notebookLogic) => notebookLogic],
        nodeAttributes: [(_, p) => [p.attributes], (nodeAttributes) => nodeAttributes],
        nodeId: [(_, p) => [p.attributes], (nodeAttributes): string => nodeAttributes.nodeId],
        nodeType: [(_, p) => [p.nodeType], (nodeType) => nodeType],
        Settings: [() => [(_, props) => props], (props): NotebookNodeSettings | null => props.Settings ?? null],
        settingsPlacement: [
            () => [(_, props) => props],
            (props): NotebookNodeSettingsPlacement => props.settingsPlacement ?? 'left',
        ],

        title: [
            (s) => [s.titlePlaceholder, s.nodeAttributes],
            (titlePlaceholder, nodeAttributes) => nodeAttributes.title || titlePlaceholder,
        ],
        // TODO: Fix the typing of nodeAttributes
        children: [(s) => [s.nodeAttributes], (nodeAttributes): NotebookNodeResource[] => nodeAttributes.children],

        exportedGlobals: [
            (s) => [s.nodeAttributes],
            (nodeAttributes): { name: string; type: string }[] => nodeAttributes.globalsExportedWithTypes ?? [],
        ],
        pythonExecution: [
            (s) => [s.nodeAttributes],
            (nodeAttributes): PythonExecutionResult | null => nodeAttributes.pythonExecution ?? null,
        ],
        displayedGlobals: [
            (s) => [s.exportedGlobals, s.pythonExecution],
            (exportedGlobals, pythonExecution): { name: string; type: string }[] => {
                if (!pythonExecution?.variables?.length) {
                    return exportedGlobals
                }

                const typeByName = new Map<string, string>(
                    pythonExecution.variables.map((variable: PythonExecutionVariable) => [variable.name, variable.type])
                )
                return exportedGlobals.map(({ name, type }) => ({
                    name,
                    type: typeByName.get(name) ?? type,
                }))
            },
        ],

        pythonNodeIndex: [
            (s) => [s.pythonNodeSummaries, s.nodeId],
            (pythonNodeSummaries, nodeId) => pythonNodeSummaries.findIndex((node) => node.nodeId === nodeId),
        ],

        downstreamPythonNodes: [
            (s) => [s.pythonNodeSummaries, s.pythonNodeIndex],
            (pythonNodeSummaries, pythonNodeIndex) =>
                pythonNodeIndex >= 0 ? pythonNodeSummaries.slice(pythonNodeIndex + 1) : [],
        ],

        usageByVariable: [
            (s) => [s.downstreamPythonNodes, s.exportedGlobals],
            (downstreamPythonNodes, exportedGlobals): Record<string, VariableUsage[]> => {
                const usageMap: Record<string, VariableUsage[]> = {}

                exportedGlobals.forEach(({ name }) => {
                    const usages = downstreamPythonNodes.flatMap((node) =>
                        node.globalsUsed.includes(name)
                            ? [
                                  {
                                      nodeId: node.nodeId,
                                      pythonIndex: node.pythonIndex,
                                      title: node.title,
                                  },
                              ]
                            : []
                    )

                    usageMap[name] = usages
                })

                return usageMap
            },
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
            if (values.notebookLogic.values.editingNodeIds[values.nodeId]) {
                values.notebookLogic.actions.setEditingNodeEditing(values.nodeId, false)
            }
        },

        selectNode: ({ scroll }) => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            const editor = values.notebookLogic.values.editor

            if (editor) {
                editor.setSelection(pos)
                if (scroll ?? true) {
                    editor.scrollToSelection()
                }
            }
        },

        navigateToNode: ({ nodeId }) => {
            const targetLogic = values.notebookLogic.values.findNodeLogicById(nodeId)
            targetLogic?.actions.selectNode()
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
            const isEditing = values.notebookLogic.values.editingNodeIds[values.nodeId]
            const shouldShowThis = typeof visible === 'boolean' ? visible : !isEditing

            props.notebookLogic.actions.setEditingNodeEditing(values.nodeId, shouldShowThis)
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

                    if (key === 'title') {
                        return `title='${JSON.stringify(value)}'`
                    }

                    return `${key}='${btoa(JSON.stringify(value))}'`
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
        runPythonNode: async ({ code }) => {
            if (props.nodeType !== NotebookNodeType.Python) {
                return
            }
            const notebook = values.notebook
            if (!notebook) {
                return
            }
            await runPythonCell({
                notebookId: notebook.short_id,
                code,
                exportedGlobals: values.exportedGlobals,
                updateAttributes: actions.updateAttributes,
                setPythonRunLoading: actions.setPythonRunLoading,
            })
        },

        runPythonNodeWithMode: async ({ mode }) => {
            if (props.nodeType !== NotebookNodeType.Python) {
                return
            }
            const notebook = values.notebook
            if (!notebook) {
                return
            }

            const currentIndex = values.pythonNodeSummaries.findIndex((node) => node.nodeId === values.nodeId)
            if (currentIndex === -1 || mode === 'auto' || mode === 'cell') {
                await actions.runPythonNode({ code: (values.nodeAttributes as { code?: string }).code ?? '' })
                return
            }

            const nodesToRun =
                mode === 'cell_upstream'
                    ? values.pythonNodeSummaries.slice(0, currentIndex + 1)
                    : values.pythonNodeSummaries.slice(currentIndex)

            const nodesToRunWithLogic = nodesToRun
                .map((node) => ({
                    node,
                    nodeLogic: values.notebookLogic.values.findNodeLogicById(node.nodeId),
                }))
                .filter(
                    (
                        entry
                    ): entry is {
                        node: (typeof nodesToRun)[number]
                        nodeLogic: BuiltLogic<notebookNodeLogicType>
                    } => !!entry.nodeLogic
                )

            nodesToRunWithLogic.forEach(({ nodeLogic }) => nodeLogic.actions.setPythonRunQueued(true))

            try {
                for (const { node, nodeLogic } of nodesToRunWithLogic) {
                    nodeLogic.actions.setPythonRunQueued(false)
                    const nodeCode = (nodeLogic.values.nodeAttributes as { code?: string }).code ?? node.code ?? ''
                    const executed = await runPythonCell({
                        notebookId: notebook.short_id,
                        code: nodeCode,
                        exportedGlobals: nodeLogic.values.exportedGlobals,
                        updateAttributes: nodeLogic.actions.updateAttributes,
                        setPythonRunLoading: nodeLogic.actions.setPythonRunLoading,
                    })

                    if (!executed) {
                        break
                    }
                }
            } finally {
                nodesToRunWithLogic.forEach(({ nodeLogic }) => nodeLogic.actions.setPythonRunQueued(false))
            }
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
