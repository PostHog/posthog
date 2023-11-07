import {
    BuiltLogic,
    actions,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
    sharedListeners,
} from 'kea'
import type { notebookLogicType } from './notebookLogicType'
import { loaders } from 'kea-loaders'
import { notebooksModel, openNotebook, SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'
import { NotebookNodeType, NotebookSyncStatus, NotebookTarget, NotebookType } from '~/types'

// NOTE: Annoyingly, if we import this then kea logic type-gen generates
// two imports and fails so, we reimport it from a utils file
import { EditorRange, JSONContent, NotebookEditor } from './utils'
import api from 'lib/api'
import posthog from 'posthog-js'
import { downloadFile, slugify } from 'lib/utils'
import { lemonToast } from '@posthog/lemon-ui'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import {
    buildTimestampCommentContent,
    NotebookNodeReplayTimestampAttrs,
} from 'scenes/notebooks/Nodes/NotebookNodeReplayTimestamp'
import { NOTEBOOKS_VERSION, migrate } from './migrations/migrate'
import { router, urlToAction } from 'kea-router'

const SYNC_DELAY = 1000

export type NotebookLogicMode = 'notebook' | 'canvas'

export type NotebookLogicProps = {
    shortId: string
    mode?: NotebookLogicMode
}

async function runWhenEditorIsReady(waitForEditor: () => boolean, fn: () => any): Promise<any> {
    // TRICKY: external code doesn't know how to wait for the editor to be ready
    // so, we have to poll until it is, then run the function
    // the use-case is that we have opened a notebook, mounted this logic,
    // and then want to run commands against the editor
    // but, we are racing against it being ready

    // throw an error after 2 seconds
    const timeout = setTimeout(() => {
        throw new Error('Notebook editor not ready')
    }, 2000)

    while (!waitForEditor()) {
        await new Promise((resolve) => setTimeout(resolve, 10))
    }
    clearTimeout(timeout)

    return fn()
}

export const notebookLogic = kea<notebookLogicType>([
    props({} as NotebookLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookLogic', key]),
    key(({ shortId, mode }) => `${shortId}-${mode}`),
    connect(() => ({
        values: [notebooksModel, ['scratchpadNotebook', 'notebookTemplates']],
        actions: [notebooksModel, ['receiveNotebookUpdate']],
    })),
    actions({
        setEditor: (editor: NotebookEditor) => ({ editor }),
        editorIsReady: true,
        onEditorUpdate: true,
        onEditorSelectionUpdate: true,
        setLocalContent: (jsonContent: JSONContent, updateEditor = false) => ({ jsonContent, updateEditor }),
        clearLocalContent: true,
        setPreviewContent: (jsonContent: JSONContent) => ({ jsonContent }),
        clearPreviewContent: true,
        loadNotebook: true,
        saveNotebook: (notebook: Pick<NotebookType, 'content' | 'title'>) => ({ notebook }),
        setEditingNodeId: (editingNodeId: string | null) => ({ editingNodeId }),
        exportJSON: true,
        showConflictWarning: true,
        onUpdateEditor: true,
        registerNodeLogic: (nodeId: string, nodeLogic: BuiltLogic<notebookNodeLogicType>) => ({ nodeId, nodeLogic }),
        unregisterNodeLogic: (nodeId: string) => ({ nodeId }),
        setEditable: (editable: boolean) => ({ editable }),
        scrollToSelection: true,
        pasteAfterLastNode: (content: string) => ({
            content,
        }),
        insertAfterLastNode: (content: JSONContent) => ({
            content,
        }),

        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent, knownStartingPosition) => ({
            content,
            nodeType,
            knownStartingPosition,
        }),
        insertReplayCommentByTimestamp: (options: {
            timestamp: number
            sessionRecordingId: string
            knownStartingPosition?: number
            nodeId?: string
        }) => options,
        setShowHistory: (showHistory: boolean) => ({ showHistory }),
        setTextSelection: (selection: number | EditorRange) => ({ selection }),
        setContainerSize: (containerSize: 'small' | 'medium') => ({ containerSize }),
    }),
    reducers(({ props }) => ({
        localContent: [
            null as JSONContent | null,
            { persist: props.mode !== 'canvas', prefix: NOTEBOOKS_VERSION },
            {
                setLocalContent: (_, { jsonContent }) => jsonContent,
                clearLocalContent: () => null,
            },
        ],
        previewContent: [
            null as JSONContent | null,
            {
                setPreviewContent: (_, { jsonContent }) => jsonContent,
                clearPreviewContent: () => null,
            },
        ],
        editor: [
            null as NotebookEditor | null,
            {
                setEditor: (_, { editor }) => editor,
            },
        ],
        ready: [
            false,
            {
                setReady: () => true,
            },
        ],
        conflictWarningVisible: [
            false,
            {
                showConflictWarning: () => true,
                loadNotebookSuccess: () => false,
            },
        ],
        editingNodeId: [
            null as string | null,
            {
                setEditingNodeId: (_, { editingNodeId }) => editingNodeId,
            },
        ],
        nodeLogics: [
            {} as Record<string, BuiltLogic<notebookNodeLogicType>>,
            {
                registerNodeLogic: (state, { nodeId, nodeLogic }) => {
                    if (nodeId === null) {
                        return state
                    } else {
                        return {
                            ...state,
                            [nodeId]: nodeLogic,
                        }
                    }
                },
                unregisterNodeLogic: (state, { nodeId }) => {
                    const newState = { ...state }
                    if (nodeId !== null) {
                        delete newState[nodeId]
                    }
                    return newState
                },
            },
        ],
        shouldBeEditable: [
            false,
            {
                setEditable: (_, { editable }) => editable,
            },
        ],
        showHistory: [
            false,
            {
                setShowHistory: (_, { showHistory }) => showHistory,
            },
        ],
        containerSize: [
            'small' as 'small' | 'medium',
            {
                setContainerSize: (_, { containerSize }) => containerSize,
            },
        ],
    })),
    loaders(({ values, props, actions }) => ({
        notebook: [
            null as NotebookType | null,
            {
                loadNotebook: async () => {
                    let response: NotebookType | null = null

                    if (values.mode !== 'notebook') {
                        return null
                    }

                    if (props.shortId === SCRATCHPAD_NOTEBOOK.short_id) {
                        response = {
                            ...values.scratchpadNotebook,
                            content: null,
                            text_content: null,
                            version: 0,
                        }
                    } else if (props.shortId.startsWith('template-')) {
                        response =
                            values.notebookTemplates.find((template) => template.short_id === props.shortId) || null
                    } else {
                        response = await api.notebooks.get(props.shortId)
                    }

                    if (!response) {
                        throw new Error('Notebook not found')
                    }

                    const notebook = migrate(response)

                    if (!values.notebook && notebook.content) {
                        // If this is the first load we need to override the content fully
                        values.editor?.setContent(notebook.content)
                    }

                    return notebook
                },

                saveNotebook: async ({ notebook }) => {
                    if (!values.notebook) {
                        return values.notebook
                    }

                    try {
                        const response = await api.notebooks.update(values.notebook.short_id, {
                            version: values.notebook.version,
                            content: notebook.content,
                            text_content: values.editor?.getText() || '',
                            title: notebook.title,
                        })

                        // If the object is identical then no edits were made, so we can safely clear the local changes
                        if (notebook.content === values.localContent) {
                            actions.clearLocalContent()
                        }

                        return response
                    } catch (error: any) {
                        if (error.code === 'conflict') {
                            actions.showConflictWarning()
                            return null
                        } else {
                            throw error
                        }
                    }
                },
            },
        ],

        newNotebook: [
            null as NotebookType | null,
            {
                duplicateNotebook: async () => {
                    if (!values.content) {
                        return null
                    }

                    // We use the local content if set otherwise the notebook content. That way it supports templates, scratchpad etc.
                    const response = await api.notebooks.create({
                        content: values.content,
                        text_content: values.editor?.getText() || '',
                        title: values.title,
                    })

                    posthog.capture(`notebook duplicated`, {
                        short_id: response.short_id,
                    })

                    const source =
                        values.mode === 'canvas'
                            ? 'Canvas'
                            : values.notebook?.short_id === 'scratchpad'
                            ? 'Scratchpad'
                            : 'Template'
                    lemonToast.success(`Notebook created from ${source}!`)

                    if (values.notebook?.short_id === 'scratchpad') {
                        // If duplicating the scratchpad, we assume they don't want the scratchpad content anymore
                        actions.clearLocalContent()
                    }

                    await openNotebook(response.short_id, NotebookTarget.Auto)

                    return response
                },
            },
        ],
    })),
    selectors({
        shortId: [() => [(_, props) => props], (props): string => props.shortId],
        mode: [() => [(_, props) => props], (props): NotebookLogicMode => props.mode ?? 'notebook'],
        isTemplate: [(s) => [s.shortId], (shortId): boolean => shortId.startsWith('template-')],
        isLocalOnly: [
            () => [(_, props) => props],
            (props): boolean => {
                return props.shortId === 'scratchpad' || props.mode === 'canvas'
            },
        ],
        notebookMissing: [
            (s) => [s.notebook, s.notebookLoading, s.mode],
            (notebook, notebookLoading, mode): boolean => {
                return (['notebook', 'template'].includes(mode) && !notebook && !notebookLoading) ?? false
            },
        ],
        content: [
            (s) => [s.notebook, s.localContent, s.previewContent],
            (notebook, localContent, previewContent): JSONContent => {
                // We use the local content is set otherwise the notebook content
                return previewContent || localContent || notebook?.content || []
            },
        ],
        title: [
            (s) => [s.notebook, s.content],
            (notebook, content): string => {
                const contentTitle = content?.content?.[0].content?.[0].text || 'Untitled'
                return contentTitle || notebook?.title || 'Untitled'
            },
        ],
        syncStatus: [
            (s) => [s.notebook, s.notebookLoading, s.localContent, s.isLocalOnly, s.previewContent],
            (notebook, notebookLoading, localContent, isLocalOnly, previewContent): NotebookSyncStatus => {
                if (previewContent || notebook?.is_template) {
                    return 'synced'
                }

                if (isLocalOnly) {
                    return 'local'
                }
                if (!notebook || !localContent) {
                    return 'synced'
                }

                if (notebookLoading) {
                    return 'saving'
                }

                return 'unsaved'
            },
        ],
        editingNodeLogic: [
            (s) => [s.editingNodeId, s.nodeLogics],
            (editingNodeId, nodeLogics) =>
                Object.values(nodeLogics).find((nodeLogic) => nodeLogic.values.nodeId === editingNodeId),
        ],
        findNodeLogic: [
            (s) => [s.nodeLogics],
            (nodeLogics) => {
                return (type: NotebookNodeType, attributes: Record<string, any>): notebookNodeLogicType | null => {
                    const attrEntries = Object.entries(attributes || {})
                    return (
                        Object.values(nodeLogics).find((nodeLogic) => {
                            return (
                                nodeLogic.props.nodeType === type &&
                                attrEntries.every(
                                    ([attr, value]: [string, any]) => nodeLogic.props.attributes?.[attr] === value
                                )
                            )
                        }) ?? null
                    )
                }
            },
        ],
        findNodeLogicById: [
            (s) => [s.nodeLogics],
            (nodeLogics) => {
                return (id: string) => {
                    return Object.values(nodeLogics).find((nodeLogic) => nodeLogic.values.nodeId === id) ?? null
                }
            },
        ],

        nodeLogicsWithChildren: [
            (s) => [s.nodeLogics, s.content],
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            (nodeLogics, _content) => {
                // NOTE: _content is not but is needed to retrigger as it could mean the children have changed
                return Object.values(nodeLogics).filter((nodeLogic) => nodeLogic.props.attributes?.children)
            },
        ],

        isShowingLeftColumn: [
            (s) => [s.editingNodeId, s.showHistory, s.containerSize],
            (editingNodeId, showHistory, containerSize) => {
                return showHistory || (!!editingNodeId && containerSize !== 'small')
            },
        ],

        isEditable: [
            (s) => [s.shouldBeEditable, s.previewContent],
            (shouldBeEditable, previewContent) => shouldBeEditable && !previewContent,
        ],
    }),
    sharedListeners(({ values, actions }) => ({
        onNotebookChange: () => {
            // Keep the list logic up to date with any changes
            if (values.notebook && values.notebook.short_id !== SCRATCHPAD_NOTEBOOK.short_id) {
                actions.receiveNotebookUpdate(values.notebook)
            }
        },
    })),
    listeners(({ values, actions, sharedListeners, cache }) => ({
        insertAfterLastNode: async ({ content }) => {
            await runWhenEditorIsReady(
                () => !!values.editor,
                () => {
                    let insertionPosition = 0
                    let nextNode = values.editor?.nextNode(insertionPosition)
                    while (nextNode) {
                        insertionPosition = nextNode.position
                        nextNode = values.editor?.nextNode(insertionPosition)
                    }

                    values.editor?.insertContentAfterNode(insertionPosition, content)
                }
            )
        },
        pasteAfterLastNode: async ({ content }) => {
            await runWhenEditorIsReady(
                () => !!values.editor,
                () => {
                    const endPosition = values.editor?.getEndPosition() || 0
                    values.editor?.pasteContent(endPosition, content)
                }
            )
        },
        insertAfterLastNodeOfType: async ({ content, nodeType, knownStartingPosition }) => {
            await runWhenEditorIsReady(
                () => !!values.editor,
                () => {
                    let insertionPosition = knownStartingPosition
                    let nextNode = values.editor?.nextNode(insertionPosition)
                    while (nextNode && values.editor?.hasChildOfType(nextNode.node, nodeType)) {
                        insertionPosition = nextNode.position
                        nextNode = values.editor?.nextNode(insertionPosition)
                    }

                    values.editor?.insertContentAfterNode(insertionPosition, content)
                }
            )
        },
        insertReplayCommentByTimestamp: async ({ timestamp, sessionRecordingId, knownStartingPosition, nodeId }) => {
            await runWhenEditorIsReady(
                () => !!values.editor,
                () => {
                    let insertionPosition =
                        knownStartingPosition || values.editor?.findNodePositionByAttrs({ id: sessionRecordingId })
                    let nextNode = values.editor?.nextNode(insertionPosition)
                    while (nextNode && values.editor?.hasChildOfType(nextNode.node, NotebookNodeType.ReplayTimestamp)) {
                        const candidateTimestampAttributes = nextNode.node.content.firstChild
                            ?.attrs as NotebookNodeReplayTimestampAttrs
                        const nextNodePlaybackTime = candidateTimestampAttributes.playbackTime || -1
                        if (nextNodePlaybackTime <= timestamp) {
                            insertionPosition = nextNode.position
                            nextNode = values.editor?.nextNode(insertionPosition)
                        } else {
                            nextNode = null
                        }
                    }

                    values.editor?.insertContentAfterNode(
                        insertionPosition,
                        buildTimestampCommentContent({
                            playbackTime: timestamp,
                            sessionRecordingId,
                            sourceNodeId: nodeId,
                        })
                    )
                }
            )
        },
        setLocalContent: async ({ updateEditor, jsonContent }, breakpoint) => {
            if (values.previewContent) {
                // We don't want to modify the content if we are viewing a preview
                return
            }
            if (updateEditor) {
                values.editor?.setContent(jsonContent)
            }

            await breakpoint(SYNC_DELAY)

            if (values.mode === 'canvas') {
                // TODO: We probably want this to be configurable
                cache.lastState = btoa(JSON.stringify(jsonContent))
                router.actions.replace(
                    router.values.currentLocation.pathname,
                    router.values.currentLocation.searchParams,
                    {
                        ...router.values.currentLocation.hashParams,
                        state: cache.lastState,
                    }
                )
            }

            posthog.capture('notebook content changed', {
                short_id: values.notebook?.short_id,
            })

            if (!values.isLocalOnly && values.content && !values.notebookLoading) {
                actions.saveNotebook({
                    content: values.content,
                    title: values.title,
                })
            }
        },

        setPreviewContent: async () => {
            values.editor?.setContent(values.content)
        },
        clearPreviewContent: async () => {
            values.editor?.setContent(values.content)
        },
        setShowHistory: async ({ showHistory }) => {
            if (!showHistory) {
                actions.clearPreviewContent()
            }
        },

        onEditorUpdate: () => {
            if (!values.editor) {
                return
            }
            const jsonContent = values.editor.getJSON()

            actions.setLocalContent(jsonContent)
            actions.onUpdateEditor()
        },
        setEditor: () => {
            values.editor?.setContent(values.content)
        },

        saveNotebookSuccess: sharedListeners.onNotebookChange,
        loadNotebookSuccess: sharedListeners.onNotebookChange,

        exportJSON: () => {
            const file = new File(
                [JSON.stringify(values.editor?.getJSON(), null, 2)],
                `${slugify(values.title ?? 'untitled')}.ph-notebook.json`,
                { type: 'application/json' }
            )

            downloadFile(file)
        },

        onEditorSelectionUpdate: () => {
            if (values.editor) {
                actions.onUpdateEditor()
            }
        },
        scrollToSelection: () => {
            if (values.editor) {
                values.editor.scrollToSelection()
            }
        },
        setEditingNodeId: () => {
            values.editingNodeLogic?.actions.selectNode()
        },

        setTextSelection: ({ selection }) => {
            queueMicrotask(() => {
                values.editor?.setTextSelection(selection)
            })
        },
    })),

    urlToAction(({ values, actions, cache }) => ({
        '*': (_, _search, hashParams) => {
            if (values.mode === 'canvas' && hashParams?.state) {
                if (cache.lastState === hashParams.state) {
                    return
                }

                actions.setLocalContent(JSON.parse(atob(hashParams.state)))
            }
        },
    })),
])
