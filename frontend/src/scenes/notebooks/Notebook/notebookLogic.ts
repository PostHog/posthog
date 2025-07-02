import { lemonToast } from '@posthog/lemon-ui'
import { actions, beforeUnmount, BuiltLogic, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { base64Decode, base64Encode, downloadFile, slugify } from 'lib/utils'
import posthog from 'posthog-js'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import {
    buildTimestampCommentContent,
    NotebookNodeReplayTimestampAttrs,
} from 'scenes/notebooks/Nodes/NotebookNodeReplayTimestamp'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { notebooksModel, openNotebook, SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'
import {
    AccessControlLevel,
    ActivityScope,
    CommentType,
    NotebookNodeType,
    NotebookSyncStatus,
    NotebookTarget,
    NotebookType,
    SidePanelTab,
} from '~/types'

import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { migrate, NOTEBOOKS_VERSION } from './migrations/migrate'
import type { notebookLogicType } from './notebookLogicType'
// NOTE: Annoyingly, if we import this then kea logic type-gen generates
// two imports and fails so, we reimport it from a utils file
import { EditorRange, JSONContent, NotebookEditor } from './utils'

const SYNC_DELAY = 1000
const NOTEBOOK_REFRESH_MS = window.location.origin === 'http://localhost:8000' ? 5000 : 30000

export type NotebookLogicMode = 'notebook' | 'canvas'

export type NotebookLogicProps = {
    shortId: string
    mode?: NotebookLogicMode
    target?: NotebookTarget
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
    connect((props: NotebookLogicProps) => ({
        values: [
            notebooksModel,
            ['scratchpadNotebook', 'notebookTemplates'],
            commentsLogic({
                scope: ActivityScope.NOTEBOOK,
                item_id: props.shortId,
            }),
            ['comments', 'itemContext'],
        ],
        actions: [
            notebooksModel,
            ['receiveNotebookUpdate'],
            sidePanelStateLogic,
            ['openSidePanel'],
            commentsLogic({
                scope: ActivityScope.NOTEBOOK,
                item_id: props.shortId,
            }),
            ['setItemContext', 'maybeLoadComments'],
        ],
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
        scheduleNotebookRefresh: true,
        saveNotebook: (notebook: Pick<NotebookType, 'content' | 'title'>) => ({ notebook }),
        renameNotebook: (title: string) => ({ title }),
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
        insertComment: (context: Record<string, any>) => ({ context }),
        selectComment: (itemContextId: string) => ({ itemContextId }),
        openShareModal: true,
        closeShareModal: true,
        setAccessDeniedToNotebook: true,
    }),
    reducers(({ props }) => ({
        isShareModalOpen: [
            false,
            {
                openShareModal: () => true,
                closeShareModal: () => false,
            },
        ],
        accessDeniedToNotebook: [false, { setAccessDeniedToNotebook: () => true }],
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
                    }
                    return {
                        ...state,
                        [nodeId]: nodeLogic,
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
                            user_access_level: AccessControlLevel.Editor,
                        }
                    } else if (props.shortId.startsWith('template-')) {
                        response =
                            values.notebookTemplates.find((template) => template.short_id === props.shortId) || null
                        if (!response) {
                            return null
                        }
                    } else {
                        try {
                            response = await api.notebooks.get(props.shortId, undefined, {
                                'If-None-Match': values.notebook?.version,
                            })
                        } catch (e: any) {
                            if (e.status === 403 && e.code === 'permission_denied') {
                                actions.setAccessDeniedToNotebook()
                            } else if (e.status === 304) {
                                // Indicates nothing has changed
                                return values.notebook
                            } else if (e.status === 404) {
                                return null
                            }
                            throw e
                        }
                    }

                    const notebook = await migrate(response)

                    if (notebook.content && (!values.notebook || values.notebook.version !== notebook.version)) {
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
                        refreshTreeItem('notebook', String(values.notebook.short_id))
                        return response
                    } catch (error: any) {
                        if (error.code === 'conflict') {
                            actions.showConflictWarning()
                            return null
                        }
                        throw error
                    }
                },
                renameNotebook: async ({ title }) => {
                    if (!values.notebook) {
                        return values.notebook
                    }
                    const response = await api.notebooks.update(values.notebook.short_id, { title })
                    refreshTreeItem('notebook', String(values.notebook.short_id))
                    return response
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

                    await openNotebook(response.short_id, props.target ?? NotebookTarget.Scene)

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
            (s) => [(_, props) => props, s.isTemplate],
            (props, isTemplate): boolean => {
                return props.shortId === 'scratchpad' || props.mode === 'canvas' || isTemplate
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
            (s) => [s.shouldBeEditable, s.previewContent, s.notebook, s.mode],
            (shouldBeEditable, previewContent, notebook, mode) =>
                mode === 'canvas' || (shouldBeEditable && !previewContent && notebook?.user_access_level === 'editor'),
        ],
    }),
    listeners(({ values, actions, cache }) => ({
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
            if (values.mode !== 'canvas' && values.notebook?.user_access_level !== 'editor') {
                actions.clearLocalContent()
                return
            }

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
                cache.lastState = base64Encode(JSON.stringify(jsonContent))
                router.actions.replace(
                    router.values.currentLocation.pathname,
                    router.values.currentLocation.searchParams,
                    {
                        ...router.values.currentLocation.hashParams,
                        '🦔': cache.lastState,
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

        saveNotebookSuccess: actions.scheduleNotebookRefresh,
        loadNotebookSuccess: () => {
            actions.scheduleNotebookRefresh()
            actions.maybeLoadComments()
        },

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

        scheduleNotebookRefresh: () => {
            if (values.mode !== 'notebook') {
                return
            }
            clearTimeout(cache.refreshTimeout)
            cache.refreshTimeout = setTimeout(() => {
                actions.loadNotebook()
            }, NOTEBOOK_REFRESH_MS)
        },

        // Comments
        insertComment: ({ context }) => {
            actions.openSidePanel(SidePanelTab.Discussion)

            actions.setItemContext(context, (result) => {
                if (!result.sent && values.editor) {
                    const pos = values.editor.findCommentPosition(context.id)
                    if (pos) {
                        values.editor.removeComment(pos)
                    }
                }
            })
            if (router.values.currentLocation.pathname !== urls.notebook(values.shortId)) {
                router.actions.push(urls.notebook(values.shortId))
            }
        },
        selectComment: ({ itemContextId }) => {
            const commentId = values.comments?.find((x) => x.item_context?.id === itemContextId)?.id

            actions.openSidePanel(SidePanelTab.Discussion, commentId)

            if (router.values.currentLocation.pathname !== urls.notebook(values.shortId)) {
                router.actions.push(urls.notebook(values.shortId))
            }
        },
    })),

    subscriptions(({ values, actions }) => ({
        notebook: (notebook?: NotebookType) => {
            // Keep the list logic up to date with any changes
            if (notebook && notebook.short_id !== SCRATCHPAD_NOTEBOOK.short_id) {
                actions.receiveNotebookUpdate(notebook)
            }
            // If the notebook ever changes, we want to reset the scheduled refresh
            actions.scheduleNotebookRefresh()
        },
        comments: (comments: CommentType[] | undefined | null) => {
            if (comments && values.editor) {
                const { editor } = values
                const commentMarkIds = comments
                    .filter((comment) => comment.item_context?.type === 'mark')
                    .map((comment) => comment.item_context?.id)

                editor.getMarks('comment').forEach((mark) => {
                    if (!commentMarkIds.includes(mark.id) && values.itemContext?.context?.id !== mark.id) {
                        editor.removeComment(mark.pos)
                    }
                })
            }
        },
    })),

    urlToAction(({ values, actions, cache }) => ({
        '*': (_, _search, hashParams) => {
            if (values.mode === 'canvas' && hashParams?.['🦔']) {
                if (cache.lastState === hashParams['🦔']) {
                    return
                }

                actions.setLocalContent(JSON.parse(base64Decode(hashParams['🦔'])))
            }
        },
    })),

    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
        const hashParams = router.values.currentLocation.hashParams
        delete hashParams['🦔']
        router.actions.replace(
            router.values.currentLocation.pathname,
            router.values.currentLocation.searchParams,
            hashParams
        )
    }),
])
