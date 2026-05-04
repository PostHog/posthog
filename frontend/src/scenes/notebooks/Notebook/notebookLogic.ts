import { sendableSteps } from '@tiptap/pm/collab'
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
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { EditorRange, JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { base64Decode, base64Encode, downloadFile, slugify } from 'lib/utils'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    SCRATCHPAD_NOTEBOOK,
    drainPendingNotebookOperations,
    notebooksModel,
    openNotebook,
} from '~/models/notebooksModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isSavedInsightNode } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    AnyPropertyFilter,
    CommentType,
    InsightShortId,
    SidePanelTab,
} from '~/types'

import {
    buildNotebookDependencyGraph,
    collectDuckSqlNodes,
    collectHogqlSqlNodes,
    collectNodeIndices,
    collectPythonNodes,
} from '../Nodes/notebookNodeContent'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
// NOTE: Annoyingly, if we import this then kea logic type-gen generates
// two imports and fails so, we reimport it from the types file
import {
    NotebookEditor,
    NotebookNodeType,
    NotebookSyncStatus,
    NotebookTarget,
    NotebookType,
    TableOfContentData,
} from '../types'
import { updateContentHeading } from '../utils'
import { NOTEBOOKS_VERSION, migrate } from './migrations/migrate'
import { notebookCollabLogic } from './notebookCollabLogic'
import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import type { notebookLogicType } from './notebookLogicType'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const SYNC_DELAY = 1000
const NOTEBOOK_REFRESH_MS = window.location.origin === 'http://localhost:8000' ? 5000 : 30000

export type NotebookLogicMode = 'notebook' | 'canvas'

export type NotebookLogicProps = {
    shortId: string
    mode?: NotebookLogicMode
    target?: NotebookTarget
    canvasFiltersOverride?: AnyPropertyFilter[]
}

async function runWhenEditorIsReady(waitForEditor: () => boolean, fn: () => any): Promise<any | null> {
    const maxWaitMs = 5000
    const startTime = Date.now()

    while (!waitForEditor()) {
        if (Date.now() - startTime > maxWaitMs) {
            console.warn('Notebook editor not ready after timeout')
            return null
        }
        await new Promise((resolve) => setTimeout(resolve, 10))
    }

    return fn()
}

function buildCommentContexts(editor: NotebookEditor, comments: CommentType[]): Record<string, string> {
    const markTexts = editor.getAllCommentTexts()
    const contexts: Record<string, string> = {}
    for (const comment of comments) {
        if (comment.source_comment || comment.item_context?.type !== 'mark') {
            continue
        }
        const text = markTexts[comment.item_context.id]
        if (text) {
            contexts[comment.id] = text
        }
    }
    return contexts
}

export const notebookLogic = kea<notebookLogicType>([
    props({} as NotebookLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookLogic', key]),
    key(({ shortId, mode }) => `${shortId}-${mode}`),

    connect((props: NotebookLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            notebooksModel,
            ['scratchpadNotebook', 'notebookTemplates'],
            commentsLogic({
                scope: ActivityScope.NOTEBOOK,
                item_id: props.shortId,
            }),
            ['comments', 'itemContext', 'selectedCommentId', 'commentContexts'],
            notebookKernelInfoLogic({ shortId: props.shortId }),
            ['kernelInfo'],
            notebookSettingsLogic,
            ['showKernelInfo', 'showTableOfContents'],
            notebookCollabLogic({ shortId: props.shortId }),
            ['ttEditor'],
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
            ['setItemContext', 'maybeLoadComments', 'setSelectedComment', 'setCommentContexts'],
            notebookCollabLogic({ shortId: props.shortId }),
            ['ackLocalSteps', 'applyRemoteSteps'],
        ],
    })),
    actions({
        setEditor: (editor: NotebookEditor) => ({ editor }),
        editorIsReady: true,
        onEditorUpdate: true,
        onEditorSelectionUpdate: true,
        setLocalContent: (jsonContent: JSONContent, updateEditor = false, skipCapture = false) => ({
            jsonContent,
            updateEditor,
            skipCapture,
        }),
        clearLocalContent: true,
        setPreviewContent: (jsonContent: JSONContent) => ({ jsonContent }),
        clearPreviewContent: true,
        loadNotebook: true,
        scheduleNotebookRefresh: true,
        saveNotebook: (notebook: Pick<NotebookType, 'content' | 'title'>) => ({ notebook }),
        renameNotebook: (title: string) => ({ title }),
        setEditingNodeEditing: (nodeId: string, editing: boolean) => ({ nodeId, editing }),
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
        addSavedInsightToNotebook: (insightShortId: InsightShortId, insertionPosition: number | null = null) => ({
            insightShortId,
            insertionPosition,
        }),
        setShowHistory: (showHistory: boolean) => ({ showHistory }),
        setTableOfContents: (tableOfContents: TableOfContentData) => ({ tableOfContents }),
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
        editingNodeIds: [
            {} as Record<string, true>,
            {
                setEditingNodeEditing: (state, { nodeId, editing }) => {
                    if (editing) {
                        return {
                            ...state,
                            [nodeId]: true,
                        }
                    }
                    if (!state[nodeId]) {
                        return state
                    }
                    const { [nodeId]: _, ...rest } = state
                    return rest
                },
                unregisterNodeLogic: (state, { nodeId }) => {
                    if (!state[nodeId]) {
                        return state
                    }
                    const { [nodeId]: _, ...rest } = state
                    return rest
                },
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
        tableOfContents: [
            [] as TableOfContentData,
            {
                setTableOfContents: (_, { tableOfContents }) => tableOfContents,
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

                    if (values.collabEnabled && values.ttEditor) {
                        const sendable = sendableSteps(values.ttEditor.state)
                        if (!sendable) {
                            return values.notebook
                        }
                        const stepsJson = sendable.steps.map((s) => s.toJSON())

                        try {
                            const response = await api.create(
                                `api/projects/@current/notebooks/${values.notebook.short_id}/collab/save/`,
                                {
                                    client_id: sendable.clientID,
                                    version: sendable.version,
                                    steps: stepsJson,
                                    content: values.editor?.getJSON(),
                                    text_content: values.editor?.getText() || '',
                                    title: notebook.title,
                                    cursor_head: values.ttEditor.state.selection.head,
                                }
                            )
                            actions.ackLocalSteps(stepsJson, String(sendable.clientID))
                            if (notebook.content === values.localContent) {
                                actions.clearLocalContent()
                            }
                            refreshTreeItem('notebook', String(values.notebook.short_id))
                            return response
                        } catch (error: any) {
                            if (error.status === 409 && error.data?.steps) {
                                // Apply the missed range (deduped by version against SSE), then retry
                                // PM-collab rebases our pending steps against the new state
                                const steps = error.data.steps as Record<string, any>[]
                                const clientIds = error.data.client_ids as string[]
                                const serverVersion = error.data.version as number
                                const firstMissedVersion = serverVersion - steps.length + 1
                                actions.applyRemoteSteps(
                                    steps.map((step, i) => ({
                                        step,
                                        clientId: clientIds[i],
                                        version: firstMissedVersion + i,
                                    }))
                                )
                                actions.saveNotebook({
                                    content: values.editor?.getJSON() ?? notebook.content,
                                    title: notebook.title,
                                })
                                return values.notebook
                            }
                            if (error.status === 410) {
                                actions.clearLocalContent()
                                actions.loadNotebook()
                                return values.notebook
                            }
                            throw error
                        }
                    }

                    // Legacy path: full-doc PATCH
                    try {
                        const response = await api.notebooks.update(values.notebook.short_id, {
                            version: values.notebook.version,
                            content: notebook.content,
                            text_content: values.editor?.getText() || '',
                            title: notebook.title,
                        })

                        if (
                            response.content &&
                            values.editor &&
                            values.localContent &&
                            notebook.content === values.localContent
                        ) {
                            const currentEditorContent = values.editor.getJSON()
                            if (JSON.stringify(response.content) !== JSON.stringify(currentEditorContent)) {
                                const currentPosition = values.editor.getCurrentPosition()
                                values.editor.setContent(response.content)
                                values.editor.setTextSelection(currentPosition)
                            }
                        }

                        // If the object is identical then no edits were made, so we can safely clear the local changes
                        if (notebook.content === values.localContent) {
                            actions.clearLocalContent()
                        }
                        refreshTreeItem('notebook', String(values.notebook.short_id))
                        return response
                    } catch (error: any) {
                        if (error.code === 'conflict') {
                            actions.clearLocalContent()
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

                    const duplicationSource =
                        values.mode === 'canvas'
                            ? 'Canvas'
                            : values.notebook?.short_id === 'scratchpad'
                              ? 'Scratchpad'
                              : values.isTemplate
                                ? 'Template'
                                : null
                    const isRegularNotebookDuplication = duplicationSource === null

                    const title = isRegularNotebookDuplication ? `${values.title} (duplicate)` : values.title

                    const content = isRegularNotebookDuplication
                        ? updateContentHeading(values.content, title)
                        : values.content

                    let textContent = values.editor?.getText() || ''
                    if (isRegularNotebookDuplication && textContent.startsWith(values.title)) {
                        textContent = title + textContent.slice(values.title.length)
                    }

                    const response = await api.notebooks.create({
                        content,
                        text_content: textContent,
                        title,
                    })

                    posthog.capture(`notebook duplicated`, {
                        short_id: response.short_id,
                    })

                    lemonToast.success(
                        duplicationSource ? `Notebook created from ${duplicationSource}!` : 'Notebook duplicated!'
                    )

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
        canvasFiltersOverride: [() => [(_, props) => props], (props) => props.canvasFiltersOverride || []],
        shortId: [(_, p) => [p.shortId], (shortId) => shortId],
        mode: [() => [(_, props) => props], (props): NotebookLogicMode => props.mode ?? 'notebook'],
        isTemplate: [(s) => [s.shortId], (shortId): boolean => shortId.startsWith('template-')],
        isLocalOnly: [
            (s) => [(_, props) => props, s.isTemplate],
            (props, isTemplate): boolean => {
                return props.shortId === 'scratchpad' || props.mode === 'canvas' || isTemplate
            },
        ],
        collabEnabled: [
            (s) => [s.featureFlags, s.isLocalOnly],
            (featureFlags: Record<string, string | boolean>, isLocalOnly: boolean): boolean =>
                !!featureFlags[FEATURE_FLAGS.NOTEBOOKS_COLLABORATION] && !isLocalOnly,
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
        editingNodeLogics: [
            (s) => [s.editingNodeIds, s.nodeLogics],
            (editingNodeIds, nodeLogics) =>
                Object.values(nodeLogics).filter((nodeLogic) => editingNodeIds[nodeLogic.values.nodeId]),
        ],
        editingNodeLogicsForLeft: [
            (s) => [s.editingNodeLogics, s.containerSize],
            (editingNodeLogics, containerSize) =>
                containerSize === 'small'
                    ? []
                    : editingNodeLogics.filter((nodeLogic) => nodeLogic.values.settingsPlacement !== 'inline'),
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
            // oxlint-disable-next-line @typescript-eslint/no-unused-vars
            (nodeLogics, _content) => {
                // NOTE: _content is not but is needed to retrigger as it could mean the children have changed
                return Object.values(nodeLogics).filter((nodeLogic) => nodeLogic.props.attributes?.children)
            },
        ],

        pythonNodeSummaries: [(s) => [s.content], (content) => collectPythonNodes(content)],
        duckSqlNodeSummaries: [(s) => [s.content], (content) => collectDuckSqlNodes(content)],
        hogqlSqlNodeSummaries: [(s) => [s.content], (content) => collectHogqlSqlNodes(content)],
        dependencyGraph: [(s) => [s.content], (content) => buildNotebookDependencyGraph(content)],

        pythonNodeIndices: [
            (s) => [s.content],
            (content) => collectNodeIndices(content, (node) => node.type === NotebookNodeType.Python),
        ],

        sqlNodeIndices: [
            (s) => [s.content],
            (content) =>
                collectNodeIndices(
                    content,
                    (node) =>
                        node.type === NotebookNodeType.Query &&
                        (isHogQLQuery(node.attrs?.query) ||
                            (node.attrs?.query?.source && isHogQLQuery(node.attrs.query.source)))
                ),
        ],
        duckSqlNodeIndices: [
            (s) => [s.content],
            (content) => collectNodeIndices(content, (node) => node.type === NotebookNodeType.DuckSQL),
        ],
        hogqlSqlNodeIndices: [
            (s) => [s.content],
            (content) => collectNodeIndices(content, (node) => node.type === NotebookNodeType.HogQLSQL),
        ],

        isShowingLeftColumn: [
            (s) => [
                s.editingNodeLogicsForLeft,
                s.showHistory,
                s.showTableOfContents,
                s.showKernelInfo,
                s.containerSize,
            ],
            (editingNodeLogicsForLeft, showHistory, showTableOfContents, showKernelInfo, containerSize) => {
                const shouldShowSettings = editingNodeLogicsForLeft.length > 0 && containerSize !== 'small'

                return showHistory || showTableOfContents || showKernelInfo || shouldShowSettings
            },
        ],

        isEditable: [
            (s) => [s.shouldBeEditable, s.previewContent, s.notebook, s.mode],
            (shouldBeEditable, previewContent, notebook, mode) =>
                shouldBeEditable &&
                (mode === 'canvas' ||
                    (!previewContent &&
                        !!notebook?.user_access_level &&
                        accessLevelSatisfied(
                            AccessControlResourceType.Notebook,
                            notebook.user_access_level,
                            AccessControlLevel.Editor
                        ))),
        ],

        insightShortIdsInNotebook: [
            (s) => [s.content],
            (content) => {
                if (!content) {
                    return []
                }
                const insightNodes = content?.content?.filter(
                    (node) => node.type === NotebookNodeType.Query && isSavedInsightNode(node?.attrs?.query)
                )
                return insightNodes?.map((node) => node?.attrs?.query?.shortId)
            },
        ],

        personUUIDFromCanvasOverride: [
            () => [(_, props) => props],
            (props: NotebookLogicProps): string | null => {
                if (!props.canvasFiltersOverride || props.canvasFiltersOverride.length === 0) {
                    return null
                }
                return props.canvasFiltersOverride.find((filter: AnyPropertyFilter) => filter.key === 'person_id')
                    ?.value as string
            },
        ],

        activeCommentMarkId: [
            (s) => [s.selectedCommentId, s.comments],
            (selectedCommentId, comments): string | null => {
                if (!selectedCommentId) {
                    return null
                }
                const comment = comments?.find((c) => c.id === selectedCommentId)
                return comment?.item_context?.type === 'mark' ? (comment.item_context.id ?? null) : null
            },
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        insertAfterLastNode: async ({ content }) => {
            await runWhenEditorIsReady(
                () => !!values.editor && (values.isLocalOnly || !!values.notebook),
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
                () => !!values.editor && (values.isLocalOnly || !!values.notebook),
                () => {
                    const endPosition = values.editor?.getEndPosition() || 0
                    values.editor?.pasteContent(endPosition, content)
                }
            )
        },
        insertAfterLastNodeOfType: async ({ content, nodeType, knownStartingPosition }) => {
            await runWhenEditorIsReady(
                () => !!values.editor && (values.isLocalOnly || !!values.notebook),
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
        addSavedInsightToNotebook: async ({ insightShortId, insertionPosition }) => {
            const content = {
                type: NotebookNodeType.Query,
                attrs: {
                    query: {
                        kind: NodeKind.SavedInsightNode,
                        shortId: insightShortId,
                    },
                },
            }

            let inserted = false

            if (insertionPosition !== null && values.editor) {
                try {
                    values.editor.insertContentAt(insertionPosition, content)
                    inserted = true
                } catch (e) {
                    console.warn('Failed to insert at position, appending to end instead', e)
                }
            }

            if (!inserted) {
                const result = await runWhenEditorIsReady(
                    () => !!values.editor && (values.isLocalOnly || !!values.notebook),
                    () => {
                        let pos = 0
                        let nextNode = values.editor?.nextNode(pos)
                        while (nextNode) {
                            pos = nextNode.position
                            nextNode = values.editor?.nextNode(pos)
                        }
                        values.editor?.insertContentAfterNode(pos, content)
                        return true
                    }
                )
                inserted = result === true
            }

            if (inserted) {
                lemonToast.success('Insight added to notebook')
            } else {
                lemonToast.warning('Could not add insight to notebook')
            }
        },
        setLocalContent: async ({ updateEditor, jsonContent, skipCapture }, breakpoint) => {
            if (
                values.mode !== 'canvas' &&
                !!values.notebook?.user_access_level &&
                !accessLevelSatisfied(
                    AccessControlResourceType.Notebook,
                    values.notebook.user_access_level,
                    AccessControlLevel.Editor
                )
            ) {
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

            if (!skipCapture) {
                posthog.capture('notebook content changed', {
                    short_id: values.notebook?.short_id,
                })
            }

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
            // Throttle onUpdateEditor to avoid performance issues with many notebook nodes
            if (cache.throttledOnUpdateEditorTimeout) {
                clearTimeout(cache.throttledOnUpdateEditorTimeout)
            }
            cache.throttledOnUpdateEditorTimeout = setTimeout(() => {
                actions.onUpdateEditor()
                cache.throttledOnUpdateEditorTimeout = null
            }, 16) // ~60fps throttling
        },
        setEditor: () => {
            // Compute contexts immediately if comments are already loaded when the editor mounts
            if (values.editor && values.comments) {
                actions.setCommentContexts(buildCommentContexts(values.editor, values.comments))
            }
        },
        onUpdateEditor: () => {
            // Re-sync previews so they track edits to text under comment marks.
            // Skip the dispatch when nothing changed to avoid re-rendering every Comment per keystroke.
            if (!values.editor || !values.comments) {
                return
            }
            const next = buildCommentContexts(values.editor, values.comments)
            const prev = values.commentContexts
            const nextKeys = Object.keys(next)
            if (nextKeys.length === Object.keys(prev).length && nextKeys.every((k) => prev[k] === next[k])) {
                return
            }
            actions.setCommentContexts(next)
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
            if (!values.editor) {
                return
            }
            // Sync the active comment to the editor cursor: when the caret enters a comment mark
            // we highlight the corresponding side-panel comment; when it leaves we clear it.
            const markId = values.editor.getAttributes('comment').id ?? null
            const targetSelectedId = markId
                ? (values.comments?.find((c) => c.item_context?.type === 'mark' && c.item_context?.id === markId)?.id ??
                  null)
                : null
            if (values.selectedCommentId !== targetSelectedId) {
                actions.setSelectedComment(targetSelectedId)
            }

            // Throttle this too to avoid excessive calls
            if (cache.throttledOnUpdateEditorTimeout) {
                clearTimeout(cache.throttledOnUpdateEditorTimeout)
            }
            cache.throttledOnUpdateEditorTimeout = setTimeout(() => {
                actions.onUpdateEditor()
                cache.throttledOnUpdateEditorTimeout = null
            }, 16) // ~60fps throttling
        },
        scrollToSelection: () => {
            if (values.editor) {
                values.editor.scrollToSelection()
            }
        },
        setEditingNodeEditing: ({ nodeId, editing }) => {
            if (!editing) {
                return
            }
            values.findNodeLogicById(nodeId)?.actions.selectNode(false)
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

            // When collab is enabled, SSE will handle real-time sync, no polling needed
            if (values.collabEnabled) {
                return
            }

            // Remove any existing refresh timeout
            cache.disposables.dispose('refreshTimeout')

            // Add new refresh timeout
            cache.disposables.add(() => {
                const refreshTimeout = setTimeout(() => {
                    actions.loadNotebook()
                }, NOTEBOOK_REFRESH_MS)
                return () => clearTimeout(refreshTimeout)
            }, 'refreshTimeout')
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

                actions.setCommentContexts(buildCommentContexts(editor, comments))
            }
        },
        activeCommentMarkId: (markId: string | null) => {
            if (!markId || !values.editor) {
                return
            }
            const pos = values.editor.findCommentPosition(markId)
            if (pos !== null) {
                values.editor.scrollToPosition(pos)
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

    afterMount(({ props }) => {
        drainPendingNotebookOperations(props.shortId)
    }),

    beforeUnmount(() => {
        const hashParams = router.values.currentLocation.hashParams
        delete hashParams['🦔']
        router.actions.replace(
            router.values.currentLocation.pathname,
            router.values.currentLocation.searchParams,
            hashParams
        )
    }),
])
