import { EventSourceMessage } from '@microsoft/fetch-event-source'
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
import { beforeUnload, router, urlToAction } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import {
    markdownCrc,
    mergeNotebookMarkdownChanges,
    tryApplyTextChanges,
} from 'lib/components/MarkdownNotebook/collaboration'
import type { TextChange } from 'lib/components/MarkdownNotebook/collaboration'
import type { MarkdownNotebookCaretPosition, RemoteNotebookCaret } from 'lib/components/MarkdownNotebook/remoteCarets'
import type { NotebookCollaborationConflict } from 'lib/components/MarkdownNotebook/types'
import { EditorRange, JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { base64Decode, base64Encode } from 'lib/utils/base64'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { downloadFile } from 'lib/utils/dom'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { objectsEqual } from 'lib/utils/objects'
import { slugify } from 'lib/utils/strings'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    SCRATCHPAD_NOTEBOOK,
    drainPendingNotebookOperations,
    notebooksModel,
    openNotebook,
} from '~/models/notebooksModel'
import type { NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { AnyResponseType, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isSavedInsightNode } from '~/queries/utils'
import {
    AccessControlLevel,
    InsightModel,
    AccessControlResourceType,
    ActivityScope,
    AnyPropertyFilter,
    CommentType,
    InsightShortId,
    SidePanelTab,
} from '~/types'

import { notebooksCollabPresenceCreate } from 'products/notebooks/frontend/generated/api'
import type { NotebookCollabCursorApi } from 'products/notebooks/frontend/generated/api.schemas'

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
import { NotebookArtifactApplyMode } from './markdownNotebookRuntime'
import {
    appendMarkdownNotebookBlock,
    buildMarkdownNotebookContent,
    convertNotebookContentToMarkdown,
    getMarkdownNotebookMarkdown,
    getMarkdownNotebookNodeId,
    getMarkdownNotebookTextContent,
    getMarkdownNotebookTitle,
    isMarkdownNotebookContent,
    notebookArtifactContentToMarkdown,
    serializeMarkdownNotebookComponent,
} from './markdownNotebookV2'
import { NOTEBOOKS_VERSION, migrate } from './migrations/migrate'
import { shouldWarnBeforeLeavingNotebook } from './notebookBeforeUnload'
import { notebookCollabLogic } from './notebookCollabLogic'
import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import type { notebookLogicType } from './notebookLogicType'
import {
    NOTEBOOK_AI_PRESENCE_CLIENT_ID,
    NOTEBOOK_AI_PRESENCE_NAME,
    NOTEBOOK_AI_PRESENCE_USER_ID,
    getNotebookMarkdownClientId,
    getNotebookPresenceParticipants,
    getNotebookRemoteParticipants,
    type NotebookPresenceParticipant,
    type NotebookPresenceState,
    type NotebookRemoteParticipant,
    pruneNotebookRemotePresence,
} from './notebookPresence'
import { notebookSettingsLogic } from './notebookSettingsLogic'

export const SYNC_DELAY = 1000
/** Markdown notebooks save on a tighter cadence so same-block co-editing feels near-realtime. */
export const MARKDOWN_SYNC_DELAY = 400
/** During continuous typing, force a save at least this often instead of debouncing forever. */
export const MARKDOWN_SYNC_MAX_DELAY = 1500
const NOTEBOOK_REFRESH_MS = window.location.origin === 'http://localhost:8000' ? 5000 : 30000

function getNotebookTextContent(content: JSONContent | null | undefined, editorText: string): string {
    return getMarkdownNotebookTextContent(content) ?? editorText
}

function keepNewestNotebookResponse(current: NotebookType | null, incoming: NotebookType | null): NotebookType | null {
    if (!current || !incoming || current.short_id !== incoming.short_id) {
        return incoming
    }

    return incoming.version < current.version ? current : incoming
}

function convertNotebookContentForRender(
    content: JSONContent | null | undefined,
    markdownNotebooksEnabled: boolean
): JSONContent | null | undefined {
    if (!markdownNotebooksEnabled || isMarkdownNotebookContent(content)) {
        return content
    }

    // Content-less notebooks (a fresh scratchpad or canvas) start as empty markdown
    // notebooks instead of falling back to the legacy TipTap editor.
    if (!content) {
        return buildMarkdownNotebookContent('')
    }

    return buildMarkdownNotebookContent(convertNotebookContentToMarkdown(content))
}

/**
 * Markdown notebooks never mount the TipTap editor, so the generic insertion actions append
 * serialized markdown blocks to the markdown source instead. Returns null when the notebook
 * isn't a markdown notebook, so callers fall through to the TipTap editor path.
 */
function appendContentToMarkdownNotebook(
    notebookContent: JSONContent,
    insertedContent: JSONContent | JSONContent[] | string
): JSONContent | null {
    if (!isMarkdownNotebookContent(notebookContent)) {
        return null
    }
    // The converter serializes the children of a doc, so a single leaf node (e.g. a dropped
    // resource) must be wrapped in an array to be serialized itself.
    const normalizedContent =
        typeof insertedContent === 'string' || Array.isArray(insertedContent) || insertedContent.type === 'doc'
            ? insertedContent
            : [insertedContent]
    return appendMarkdownNotebookBlock(notebookContent, convertNotebookContentToMarkdown(normalizedContent))
}

export type NotebookLogicMode = 'notebook' | 'canvas'

/** A markdown notebook update from the collab SSE stream or a 409 conflict body. */
export type MarkdownStreamEvent = {
    /** Notebook version this event produces. */
    version: number
    /** UTF-16 span changes transforming version-1 → version; absent means "reload". */
    diff?: TextChange[] | null
    /** CRC-32 of the base markdown; mismatch means our base diverged — reload. */
    baseCrc?: number | null
    /** Saving client's id, used to skip self-echo. */
    clientId?: string | null
}

/** Latest known caret of another client, from presence pings or update events. */
export type NotebookRemotePresenceState = NotebookPresenceState & {
    version: number
    cursor: NotebookCollabCursorApi
}

/** Remote carets older than this stop rendering; senders heartbeat well within it. */
const PRESENCE_TTL_MS = 30_000
const PRESENCE_PRUNE_INTERVAL_MS = 5_000
const PRESENCE_HEARTBEAT_MS = 10_000
/** Client-side debounce for caret pings, the floor for caret latency. */
const PRESENCE_PUBLISH_DEBOUNCE_MS = 250

function apiCursorToCaretPosition(cursor: NotebookCollabCursorApi): MarkdownNotebookCaretPosition | null {
    if (typeof cursor.node_index !== 'number') {
        return null
    }
    return { nodeIndex: cursor.node_index, offset: cursor.offset, listItemIndex: cursor.list_item_index }
}

function caretPositionToApiCursor(position: MarkdownNotebookCaretPosition): NotebookCollabCursorApi {
    return { node_index: position.nodeIndex, offset: position.offset, list_item_index: position.listItemIndex }
}

function parseRemotePresencePayload(payload: unknown): Omit<NotebookRemotePresenceState, 'lastSeenAt'> | null {
    if (typeof payload !== 'object' || payload === null) {
        return null
    }
    const candidate = payload as Record<string, unknown>
    if (
        typeof candidate.client_id !== 'string' ||
        typeof candidate.user_id !== 'number' ||
        typeof candidate.user_name !== 'string' ||
        typeof candidate.cursor !== 'object' ||
        candidate.cursor === null
    ) {
        return null
    }
    return {
        clientId: candidate.client_id,
        userId: candidate.user_id,
        userName: candidate.user_name,
        version: typeof candidate.version === 'number' ? candidate.version : 0,
        cursor: candidate.cursor as NotebookCollabCursorApi,
    }
}

export type NotebookLogicProps = {
    shortId: string
    mode?: NotebookLogicMode
    target?: NotebookTarget
    canvasFiltersOverride?: AnyPropertyFilter[]
    /**
     * Pre-loaded notebook payload for shared/exported views. When set, `loadNotebook`
     * short-circuits and uses this value instead of calling the API — anonymous shared
     * viewers can't reach `/api/projects/.../notebooks/<short_id>/`.
     */
    cachedNotebook?: NotebookType
    /**
     * Pre-serialized saved insights referenced by a shared notebook, keyed by `short_id`.
     * Each entry has computed results inlined so `NotebookNodeQuery` can seed `cachedInsight`
     * and skip the `/query/` POST that sharing tokens cannot reach.
     */
    cachedInsightsByShortId?: Record<string, InsightModel>
    /**
     * Pre-computed results for inline (non-saved-insight) ph-query nodes in a shared notebook,
     * keyed by `nodeId`. Lets `NotebookNodeQuery` seed `cachedResults` for ad-hoc queries too.
     */
    cachedInlineQueryResultsByNodeId?: Record<string, AnyResponseType>
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
            ['ttEditor', 'remoteParticipants'],
            userLogic,
            ['user'],
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
            ['ackLocalSteps', 'applyRemoteSteps', 'rebaseFailed'],
        ],
    })),
    actions({
        setEditor: (editor: NotebookEditor) => ({ editor }),
        editorIsReady: true,
        onEditorUpdate: true,
        onEditorSelectionUpdate: true,
        setAutosavePaused: (paused: boolean) => ({ paused }),
        setMarkdownEditorInteractionActive: (active: boolean) => ({ active }),
        setMarkdownAIPresenceActive: (active: boolean) => ({ active }),
        handleMarkdownEditorChange: (markdown: string) => ({ markdown }),
        setMarkdownEditorDraft: (draft: string | null) => ({ draft }),
        setMarkdownEditorBuffer: (buffered: string | null) => ({ buffered }),
        applyNotebookArtifactMarkdown: (
            content: NotebookArtifactContent,
            conversationId?: string,
            mode: NotebookArtifactApplyMode = 'replace'
        ) => ({ content, conversationId, mode }),
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
        connectMarkdownUpdateStream: true,
        disconnectMarkdownUpdateStream: true,
        /** Apply a canonical remote state (streamed diff or 409 replay) without refetching. */
        applyRemoteNotebookContent: (content: JSONContent, version: number) => ({ content, version }),
        handleMarkdownStreamEvent: (event: MarkdownStreamEvent) => ({ event }),
        processPendingMarkdownStreamEvents: true,
        handleRemotePresence: (presence: Omit<NotebookRemotePresenceState, 'lastSeenAt'>) => ({
            presence,
            receivedAt: Date.now(),
        }),
        pruneRemotePresence: () => ({ now: Date.now() }),
        /** Broadcast the local caret; null means the selection left the notebook. */
        publishMarkdownCaret: (position: MarkdownNotebookCaretPosition | null) => ({ position }),
        reportMarkdownMergeConflicts: (conflicts: NotebookCollaborationConflict[]) => ({ conflicts }),
        showMarkdownMergeConflictDetails: (conflicts: NotebookCollaborationConflict[]) => ({ conflicts }),
        dismissMarkdownMergeConflictDetails: true,
        saveNotebook: (notebook: Pick<NotebookType, 'content' | 'title'>) => ({ notebook }),
        renameNotebook: (title: string) => ({ title }),
        setEditingNodeEditing: (nodeId: string, editing: boolean) => ({ nodeId, editing }),
        exportJSON: true,
        downloadMarkdown: true,
        copyMarkdown: true,
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
        addExperimentToNotebook: (experimentId: number, insertionPosition: number | null = null) => ({
            experimentId,
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
        showCollabConflict: (params: { serverContent: JSONContent; localContent: JSONContent; localText: string }) =>
            params,
        dismissCollabConflict: true,
        discardLocalChanges: true,
        copyUnsavedToNewNotebook: true,
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
        autosavePaused: [
            false,
            {
                setAutosavePaused: (_, { paused }) => paused,
            },
        ],
        markdownEditorInteractionActive: [
            false,
            {
                setMarkdownEditorInteractionActive: (_, { active }) => active,
            },
        ],
        // The markdown the editor renders while an interaction (insert menu, toolbar) is active —
        // it freezes the editor value so logic-side content changes don't disturb the interaction.
        markdownEditorDraft: [
            null as string | null,
            {
                setMarkdownEditorDraft: (_, { draft }) => draft,
            },
        ],
        // Edits made while an interaction is active, flushed to localContent when it ends.
        markdownEditorBuffer: [
            null as string | null,
            {
                setMarkdownEditorBuffer: (_, { buffered }) => buffered,
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
        collabConflict: [
            null as {
                serverContent: JSONContent
                localContent: JSONContent
                localText: string
            } | null,
            {
                showCollabConflict: (_, params) => params,
                dismissCollabConflict: () => null,
            },
        ],
        markdownMergeConflictDetails: [
            null as NotebookCollaborationConflict[] | null,
            {
                showMarkdownMergeConflictDetails: (_, { conflicts }) => conflicts,
                dismissMarkdownMergeConflictDetails: () => null,
            },
        ],
        markdownRemotePresence: [
            {} as Record<string, NotebookRemotePresenceState>,
            {
                handleRemotePresence: (state, { presence, receivedAt }) => ({
                    ...state,
                    [presence.clientId]: { ...presence, lastSeenAt: receivedAt },
                }),
                pruneRemotePresence: (state, { now }) => pruneNotebookRemotePresence(state, now, PRESENCE_TTL_MS),
                disconnectMarkdownUpdateStream: () => ({}),
            },
        ],
        markdownAIPresenceActive: [
            false,
            {
                setMarkdownAIPresenceActive: (_, { active }) => active,
                disconnectMarkdownUpdateStream: () => false,
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
    loaders(({ values, props, actions, cache }) => ({
        notebook: [
            null as NotebookType | null,
            {
                loadNotebook: async () => {
                    let response: NotebookType | null = null

                    if (values.mode !== 'notebook') {
                        return null
                    }

                    if (props.cachedNotebook) {
                        response = props.cachedNotebook
                    } else if (props.shortId === SCRATCHPAD_NOTEBOOK.short_id) {
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

                    const notebook = await migrate(response, { skipApiUpgrade: !!values.isShared })

                    if (
                        !values.collabEnabled &&
                        notebook.content &&
                        (!values.notebook || values.notebook.version !== notebook.version)
                    ) {
                        // Push fresh server content into the editor on polling refresh (no-op on first load).
                        // Collab notebooks update via SSE, not setContent.
                        values.editor?.setContent(notebook.content)
                    }

                    return notebook
                },

                saveNotebook: async ({ notebook }) => {
                    if (!values.notebook) {
                        return values.notebook
                    }

                    // While the stale-conflict modal is open, the user's local content has diverged
                    // from the server beyond what we can merge. Don't keep retrying saves until
                    // they choose to discard or force-save — otherwise we'd loop on 410s.
                    if (values.collabConflict) {
                        return values.notebook
                    }

                    const notebookContent = notebook.content

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
                                    text_content: getNotebookTextContent(
                                        values.editor?.getJSON() ?? notebook.content,
                                        values.editor?.getText() || ''
                                    ),
                                    title: notebook.title,
                                    cursor_head: values.ttEditor.state.selection.head,
                                }
                            )
                            actions.ackLocalSteps(stepsJson, String(sendable.clientID))
                            refreshTreeItem('notebook', String(values.notebook.short_id))
                            posthog.capture('notebook saved', {
                                short_id: values.notebook.short_id,
                                save_path: 'tiptap_collab',
                                is_markdown: false,
                            })
                            return response
                        } catch (error: any) {
                            if (error.status === 409 && error.data?.steps) {
                                // prosemirror-collab rebases our pending steps over the missed range.
                                // If receiveTransaction throws, `rebaseFailed` opens the conflict modal.
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
                                if (values.collabConflict) {
                                    return values.notebook
                                }
                                actions.saveNotebook({
                                    content: values.editor?.getJSON() ?? notebook.content,
                                    title: notebook.title,
                                })
                                return values.notebook
                            }
                            if (error.status === 410) {
                                // Stream trimmed
                                actions.rebaseFailed({
                                    localContent: values.editor?.getJSON() ?? notebook.content ?? {},
                                    localText: values.editor?.getText() ?? '',
                                })
                                return values.notebook
                            }
                            posthog.capture('notebook save failed', {
                                short_id: values.notebook.short_id,
                                save_path: 'tiptap_collab',
                                is_markdown: false,
                                status: error.status,
                            })
                            throw error
                        }
                    }

                    if (values.markdownRealtimeEnabled && isMarkdownNotebookContent(notebookContent)) {
                        const baselineVersion = values.notebook.version
                        const baseMarkdown = getMarkdownNotebookMarkdown(values.notebook.content)
                        const nextMarkdown = getMarkdownNotebookMarkdown(notebookContent)
                        const nodeId = getMarkdownNotebookNodeId(values.notebook.content)

                        if (nextMarkdown === baseMarkdown) {
                            if ((notebook.title ?? '') !== (values.notebook.title ?? '')) {
                                const response = await api.notebooks.update(values.notebook.short_id, {
                                    title: notebook.title,
                                })
                                refreshTreeItem('notebook', String(values.notebook.short_id))
                                return response
                            }
                            return values.notebook
                        }

                        cache.markdownClientId = cache.markdownClientId || getNotebookMarkdownClientId()
                        try {
                            const response = await api.notebooks.markdownSave(values.notebook.short_id, {
                                client_id: cache.markdownClientId,
                                version: baselineVersion,
                                content: notebookContent,
                                text_content: getNotebookTextContent(notebookContent, ''),
                                title: notebook.title,
                                cursor: cache.lastMarkdownCaret
                                    ? caretPositionToApiCursor(cache.lastMarkdownCaret)
                                    : undefined,
                            })
                            refreshTreeItem('notebook', String(values.notebook.short_id))
                            posthog.capture('notebook saved', {
                                short_id: values.notebook.short_id,
                                save_path: 'markdown_realtime',
                                is_markdown: true,
                            })
                            return response
                        } catch (error: any) {
                            if (error.status === 409 && error.data?.updates) {
                                // Fold the missed diffs into our baseline to reconstruct the server
                                // state, merge our edits over it, and retry against the new version —
                                // all without refetching the notebook.
                                const updates = error.data.updates as {
                                    version: number
                                    diff: TextChange[]
                                    base_crc?: number | null
                                }[]
                                posthog.capture('notebook markdown save conflict retried', {
                                    short_id: values.notebook.short_id,
                                    missed_updates: updates.length,
                                })
                                let serverMarkdown: string | null = baseMarkdown
                                for (const update of updates) {
                                    if (
                                        typeof update.base_crc === 'number' &&
                                        markdownCrc(serverMarkdown) !== update.base_crc
                                    ) {
                                        serverMarkdown = null
                                        break
                                    }
                                    serverMarkdown = tryApplyTextChanges(serverMarkdown, update.diff)
                                    if (serverMarkdown === null) {
                                        break
                                    }
                                }
                                if (serverMarkdown === null) {
                                    // Replay didn't fit our baseline — reload; the editor merges
                                    // local edits over the fresh server state via remoteValue.
                                    posthog.capture('notebook markdown full reload', {
                                        short_id: values.notebook.short_id,
                                        reason: 'save_replay_failed',
                                    })
                                    actions.loadNotebook()
                                    return values.notebook
                                }
                                const serverVersion = error.data.version as number
                                const merge = mergeNotebookMarkdownChanges({
                                    baseMarkdown,
                                    localMarkdown: nextMarkdown,
                                    remoteMarkdown: serverMarkdown,
                                })
                                actions.applyRemoteNotebookContent(
                                    buildMarkdownNotebookContent(serverMarkdown, nodeId),
                                    serverVersion
                                )
                                if (merge.mergedMarkdown !== serverMarkdown) {
                                    actions.saveNotebook({
                                        content: buildMarkdownNotebookContent(merge.mergedMarkdown, nodeId),
                                        title: notebook.title,
                                    })
                                }
                                return values.notebook
                            }
                            if (error.status === 410) {
                                // Missed range not replayable (trimmed / mixed writers): full reload,
                                // the editor merges local edits over the fresh server state.
                                posthog.capture('notebook markdown full reload', {
                                    short_id: values.notebook.short_id,
                                    reason: 'stream_trimmed',
                                })
                                actions.loadNotebook()
                                return values.notebook
                            }
                            posthog.capture('notebook save failed', {
                                short_id: values.notebook.short_id,
                                save_path: 'markdown_realtime',
                                is_markdown: true,
                                status: error.status,
                            })
                            throw error
                        }
                    }

                    // Legacy path: full-doc PATCH
                    try {
                        const response = await api.notebooks.update(values.notebook.short_id, {
                            version: values.notebook.version,
                            content: notebookContent,
                            text_content: getNotebookTextContent(notebookContent, values.editor?.getText() || ''),
                            title: notebook.title,
                        })

                        if (
                            response.content &&
                            values.editor &&
                            values.localContent &&
                            notebookContent === values.localContent
                        ) {
                            const currentEditorContent = values.editor.getJSON()
                            if (JSON.stringify(response.content) !== JSON.stringify(currentEditorContent)) {
                                const currentPosition = values.editor.getCurrentPosition()
                                values.editor.setContent(response.content)
                                values.editor.setTextSelection(currentPosition)
                            }
                        }

                        refreshTreeItem('notebook', String(values.notebook.short_id))
                        posthog.capture('notebook saved', {
                            short_id: values.notebook.short_id,
                            save_path: 'legacy_patch',
                            is_markdown: isMarkdownNotebookContent(notebookContent),
                        })
                        return response
                    } catch (error: any) {
                        if (error.code === 'conflict') {
                            const currentLocalContent = values.localContent
                            const savedContent = values.notebook.content
                            if (
                                isMarkdownNotebookContent(savedContent) &&
                                isMarkdownNotebookContent(currentLocalContent)
                            ) {
                                try {
                                    const freshNotebook = await api.notebooks.get(
                                        values.notebook.short_id,
                                        undefined,
                                        {}
                                    )
                                    if (freshNotebook && isMarkdownNotebookContent(freshNotebook.content)) {
                                        // The markdown editor merges fresh server content into local edits
                                        // through its remoteValue path and re-emits the merged content,
                                        // which retries the save against the new version.
                                        refreshTreeItem('notebook', String(values.notebook.short_id))
                                        return freshNotebook
                                    }
                                } catch {
                                    // Fall through to the manual conflict path if refreshing content fails.
                                }
                            }

                            actions.clearLocalContent()
                            actions.showConflictWarning()
                            return null
                        }
                        posthog.capture('notebook save failed', {
                            short_id: values.notebook.short_id,
                            save_path: 'legacy_patch',
                            is_markdown: isMarkdownNotebookContent(notebookContent),
                            status: error.status,
                        })
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

                    let textContent = getNotebookTextContent(content, values.editor?.getText() || '')
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
    reducers({
        // Extends the loader reducer: canonical remote states (streamed diffs, 409 replays)
        // land in `notebook` without a refetch.
        notebook: {
            loadNotebookSuccess: (state, { notebook }) => keepNewestNotebookResponse(state, notebook),
            saveNotebookSuccess: (state, { notebook }) => keepNewestNotebookResponse(state, notebook),
            applyRemoteNotebookContent: (state, { content, version }) =>
                state && version > state.version ? { ...state, content, version } : state,
        },
    }),
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
            (s) => [s.featureFlags, s.isLocalOnly, s.content],
            (featureFlags: Record<string, string | boolean>, isLocalOnly: boolean, content: JSONContent): boolean =>
                !!featureFlags[FEATURE_FLAGS.NOTEBOOKS_COLLABORATION] &&
                !isLocalOnly &&
                !isMarkdownNotebookContent(content),
        ],
        markdownRealtimeEnabled: [
            (s) => [(_, props) => props, s.mode, s.isLocalOnly, s.notebook, s.content, s.featureFlags],
            (
                props: NotebookLogicProps,
                mode: NotebookLogicMode,
                isLocalOnly: boolean,
                notebook: NotebookType | null,
                content: JSONContent,
                featureFlags: Record<string, string | boolean>
            ): boolean =>
                mode === 'notebook' &&
                !props.cachedNotebook &&
                !isLocalOnly &&
                !!notebook &&
                (isMarkdownNotebookContent(notebook.content) ||
                    (!!featureFlags[FEATURE_FLAGS.MARKDOWN_NOTEBOOKS] && isMarkdownNotebookContent(content))),
        ],
        notebookMissing: [
            (s) => [s.notebook, s.notebookLoading, s.mode],
            (notebook, notebookLoading, mode): boolean => {
                return (['notebook', 'template'].includes(mode) && !notebook && !notebookLoading) ?? false
            },
        ],
        markdownRemoteCarets: [
            (s) => [s.markdownRemotePresence],
            (markdownRemotePresence): RemoteNotebookCaret[] => {
                const carets: RemoteNotebookCaret[] = []
                for (const presence of Object.values(markdownRemotePresence)) {
                    const position = apiCursorToCaretPosition(presence.cursor)
                    if (position) {
                        carets.push({
                            clientId: presence.clientId,
                            userName: presence.userName,
                            color: getSeriesColor(presence.userId),
                            position,
                            version: presence.version,
                        })
                    }
                }
                return carets
            },
        ],
        markdownRemoteParticipants: [
            (s) => [s.markdownRemotePresence],
            (markdownRemotePresence): NotebookRemoteParticipant[] =>
                getNotebookRemoteParticipants(markdownRemotePresence),
        ],
        notebookPresenceParticipants: [
            (s) => [s.user, s.markdownRemoteParticipants, s.remoteParticipants, s.markdownAIPresenceActive],
            (
                user,
                markdownRemoteParticipants: NotebookRemoteParticipant[],
                remoteParticipants: NotebookRemoteParticipant[],
                markdownAIPresenceActive: boolean
            ): NotebookPresenceParticipant[] => {
                const participants = getNotebookPresenceParticipants(
                    user,
                    markdownRemoteParticipants.length > 0 ? markdownRemoteParticipants : remoteParticipants
                )
                if (!markdownAIPresenceActive) {
                    return participants
                }
                const aiParticipant: NotebookPresenceParticipant = {
                    clientId: NOTEBOOK_AI_PRESENCE_CLIENT_ID,
                    userId: NOTEBOOK_AI_PRESENCE_USER_ID,
                    userName: NOTEBOOK_AI_PRESENCE_NAME,
                    lastSeenAt: 0,
                    isAI: true,
                }
                const [firstParticipant, ...remainingParticipants] = participants
                return firstParticipant ? [firstParticipant, aiParticipant, ...remainingParticipants] : [aiParticipant]
            },
        ],
        content: [
            (s) => [s.notebook, s.localContent, s.previewContent, s.featureFlags],
            (
                notebook: NotebookType | null,
                localContent: JSONContent | null,
                previewContent: JSONContent | null,
                featureFlags: Record<string, string | boolean>
            ): JSONContent => {
                const content = previewContent || localContent || notebook?.content
                return convertNotebookContentForRender(content, !!featureFlags[FEATURE_FLAGS.MARKDOWN_NOTEBOOKS]) || []
            },
        ],
        markdownEditorMarkdown: [(s) => [s.content], (content): string => getMarkdownNotebookMarkdown(content)],
        markdownEditorNodeId: [(s) => [s.content], (content): string => getMarkdownNotebookNodeId(content)],
        markdownEditorValue: [
            (s) => [s.markdownEditorDraft, s.markdownEditorMarkdown],
            (markdownEditorDraft, markdownEditorMarkdown): string => markdownEditorDraft ?? markdownEditorMarkdown,
        ],
        title: [
            (s) => [s.notebook, s.content],
            (notebook, content): string => {
                const firstTextNode = content?.content?.[0]?.content?.[0]
                const contentTitle = isMarkdownNotebookContent(content)
                    ? getMarkdownNotebookTitle(content)
                    : typeof firstTextNode?.text === 'string'
                      ? firstTextNode.text
                      : null
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
            (s) => [s.editingNodeIds, s.nodeLogics, s.isShared],
            (editingNodeIds, nodeLogics, isShared) => {
                // Editing UI is meaningless for anonymous shared viewers and `editingNodeIds` can
                // arrive pre-populated from persisted local state — zero it out at the source so
                // the Settings panel never renders for them.
                if (isShared) {
                    return []
                }
                return Object.values(nodeLogics).filter((nodeLogic) => editingNodeIds[nodeLogic.values.nodeId])
            },
        ],
        editingNodeLogicsForLeft: [
            (s) => [s.editingNodeLogics, s.containerSize, s.content],
            (
                editingNodeLogics: BuiltLogic<notebookNodeLogicType>[],
                containerSize: 'small' | 'medium',
                content: JSONContent
            ) =>
                containerSize === 'small' || isMarkdownNotebookContent(content)
                    ? []
                    : editingNodeLogics.filter(
                          (nodeLogic: BuiltLogic<notebookNodeLogicType>) =>
                              nodeLogic.values.settingsPlacement !== 'inline'
                      ),
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
                s.content,
            ],
            (
                editingNodeLogicsForLeft: BuiltLogic<notebookNodeLogicType>[],
                showHistory: boolean,
                showTableOfContents: boolean,
                showKernelInfo: boolean,
                containerSize: 'small' | 'medium',
                content: JSONContent
            ) => {
                const isMarkdownNotebook = isMarkdownNotebookContent(content)
                const shouldShowSettings =
                    !isMarkdownNotebook && editingNodeLogicsForLeft.length > 0 && containerSize !== 'small'
                const shouldShowTableOfContents = !isMarkdownNotebook && showTableOfContents
                const shouldShowKernelInfo = !isMarkdownNotebook && showKernelInfo

                return showHistory || shouldShowTableOfContents || shouldShowKernelInfo || shouldShowSettings
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

        isShared: [() => [(_, props) => props.cachedNotebook], (cachedNotebook): boolean => !!cachedNotebook],

        cachedInsightsByShortId: [
            () => [(_, props) => props.cachedInsightsByShortId],
            (cachedInsightsByShortId): Record<string, InsightModel> => cachedInsightsByShortId ?? {},
        ],

        cachedInlineQueryResultsByNodeId: [
            () => [(_, props) => props.cachedInlineQueryResultsByNodeId],
            (cachedInlineQueryResultsByNodeId): Record<string, AnyResponseType> =>
                cachedInlineQueryResultsByNodeId ?? {},
        ],

        getSharedCachedInsight: [
            (s) => [s.isShared, s.cachedInsightsByShortId],
            (isShared, cachedInsightsByShortId) =>
                (shortId: string | null | undefined): InsightModel | null => {
                    if (!isShared || !shortId) {
                        return null
                    }
                    return cachedInsightsByShortId[shortId] ?? null
                },
        ],
        getSharedCachedInlineQueryResults: [
            (s) => [s.isShared, s.cachedInlineQueryResultsByNodeId],
            (isShared, cachedInlineQueryResultsByNodeId) =>
                (nodeId: string | null | undefined): AnyResponseType | null => {
                    if (!isShared || !nodeId) {
                        return null
                    }
                    return cachedInlineQueryResultsByNodeId[nodeId] ?? null
                },
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

        experimentIdsInNotebook: [
            (s) => [s.content],
            (content): number[] => {
                if (!content) {
                    return []
                }
                const experimentNodes = content?.content?.filter((node) => node.type === NotebookNodeType.Experiment)
                return experimentNodes?.map((node) => node?.attrs?.id).filter(Boolean) as number[]
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
        connectMarkdownUpdateStream: () => {
            if (!values.markdownRealtimeEnabled) {
                return
            }
            cache.markdownClientId = cache.markdownClientId || getNotebookMarkdownClientId()

            cache.disposables.add(
                () => {
                    const controller = new AbortController()

                    const onMessage = (msg: EventSourceMessage): void => {
                        if (msg.id) {
                            cache.markdownUpdateStreamLastEventId = msg.id
                        }

                        if (msg.event === 'presence' && msg.data) {
                            try {
                                const presence = parseRemotePresencePayload(JSON.parse(msg.data))
                                if (presence && presence.clientId !== cache.markdownClientId) {
                                    actions.handleRemotePresence(presence)
                                }
                            } catch (e) {
                                posthog.captureException(e as Error, { action: 'notebook presence stream parse' })
                            }
                            return
                        }

                        if (msg.event !== 'update' && msg.event !== 'step') {
                            return
                        }

                        let version = msg.id ? parseInt(msg.id.split('-', 1)[0], 10) : null
                        let diff: TextChange[] | null = null
                        let baseCrc: number | null = null
                        let clientId: string | null = null
                        if (msg.event === 'update' && msg.data) {
                            try {
                                const payload = JSON.parse(msg.data) as {
                                    version?: unknown
                                    diff?: unknown
                                    base_crc?: unknown
                                    client_id?: unknown
                                }
                                if (typeof payload.version === 'number') {
                                    version = payload.version
                                }
                                diff = Array.isArray(payload.diff) ? (payload.diff as TextChange[]) : null
                                baseCrc = typeof payload.base_crc === 'number' ? payload.base_crc : null
                                clientId = typeof payload.client_id === 'string' ? payload.client_id : null

                                // Saves piggyback the author's caret so it moves in the same
                                // paint as the text change lands. CAS entries carry no version
                                // field — the stream id (already folded into `version`) is it.
                                const presence = parseRemotePresencePayload(payload)
                                if (presence && presence.clientId !== cache.markdownClientId) {
                                    actions.handleRemotePresence({ ...presence, version: version ?? presence.version })
                                }
                            } catch (e) {
                                posthog.captureException(e as Error, { action: 'notebook markdown stream parse' })
                            }
                        }

                        if (!version || !Number.isFinite(version)) {
                            return
                        }

                        actions.handleMarkdownStreamEvent({ version, diff, baseCrc, clientId })
                    }

                    const onError = (error: any): void => {
                        if (controller.signal.aborted) {
                            return
                        }
                        const message = error instanceof Error ? error.message : String(error)
                        posthog.captureException(error instanceof Error ? error : new Error(message), {
                            action: 'notebook markdown stream',
                        })
                    }

                    const onClose = (): void => {
                        if (controller.signal.aborted) {
                            return
                        }
                        actions.connectMarkdownUpdateStream()
                    }

                    void api.notebooks
                        .collabStream(values.shortId, {
                            onMessage,
                            onError,
                            onClose,
                            signal: controller.signal,
                            lastEventId: cache.markdownUpdateStreamLastEventId,
                        })
                        .catch((error) => {
                            if (controller.signal.aborted) {
                                return
                            }
                            onError(error)
                            actions.connectMarkdownUpdateStream()
                        })

                    return () => controller.abort()
                },
                'markdownUpdateStream',
                { pauseOnPageHidden: false }
            )

            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => actions.pruneRemotePresence(), PRESENCE_PRUNE_INTERVAL_MS)
                return () => window.clearInterval(intervalId)
            }, 'markdownPresencePrune')

            // Re-announce the caret while idle so it outlives the receivers' TTL. Pausing on
            // hidden tabs is deliberate: backgrounded editors' carets fade out remotely.
            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => {
                    if (cache.lastMarkdownCaret) {
                        actions.publishMarkdownCaret(cache.lastMarkdownCaret)
                    }
                }, PRESENCE_HEARTBEAT_MS)
                return () => window.clearInterval(intervalId)
            }, 'markdownPresenceHeartbeat')
        },
        disconnectMarkdownUpdateStream: () => {
            cache.disposables.dispose('markdownUpdateStream')
            cache.disposables.dispose('markdownPresencePrune')
            cache.disposables.dispose('markdownPresenceHeartbeat')
            cache.markdownUpdateStreamLastEventId = undefined
            cache.pendingMarkdownStreamEvents = []
        },
        publishMarkdownCaret: async ({ position }, breakpoint) => {
            cache.lastMarkdownCaret = position
            if (!position || !values.markdownRealtimeEnabled || !values.isEditable || !values.notebook) {
                return
            }
            await breakpoint(PRESENCE_PUBLISH_DEBOUNCE_MS)

            // Skip unchanged positions between heartbeats: selectionchange fires on scroll
            // and re-renders without the caret actually moving.
            const serialized = JSON.stringify(position)
            if (
                cache.lastSentMarkdownCaret === serialized &&
                Date.now() - (cache.lastSentMarkdownCaretAt ?? 0) < PRESENCE_HEARTBEAT_MS
            ) {
                return
            }

            cache.markdownClientId = cache.markdownClientId || getNotebookMarkdownClientId()
            try {
                await notebooksCollabPresenceCreate(String(getCurrentTeamId()), values.notebook.short_id, {
                    client_id: cache.markdownClientId,
                    version: values.notebook.version,
                    cursor: caretPositionToApiCursor(position),
                })
                cache.lastSentMarkdownCaret = serialized
                cache.lastSentMarkdownCaretAt = Date.now()
            } catch {
                // Presence is lossy by design; the next ping self-heals.
            }
        },
        handleMarkdownStreamEvent: ({ event }) => {
            if (event.clientId && event.clientId === cache.markdownClientId) {
                // Our own save echoing back; the save response already advanced our state.
                return
            }
            const notebook = values.notebook
            if (!notebook || event.version <= notebook.version) {
                return
            }
            if (values.notebookLoading) {
                // A load or save is mid-flight and lastEventId has already advanced past this
                // event, so dropping it would leave us permanently stale. Queue and replay
                // once the loader settles.
                cache.pendingMarkdownStreamEvents = [...(cache.pendingMarkdownStreamEvents ?? []), event]
                return
            }
            if (event.diff && event.version === notebook.version + 1 && isMarkdownNotebookContent(notebook.content)) {
                const baseMarkdown = getMarkdownNotebookMarkdown(notebook.content)
                const baseMatches = typeof event.baseCrc !== 'number' || markdownCrc(baseMarkdown) === event.baseCrc
                const nextMarkdown = baseMatches ? tryApplyTextChanges(baseMarkdown, event.diff) : null
                if (nextMarkdown !== null) {
                    // Diffs are exact version transitions, so the result is canonical server
                    // state — no GET needed. The editor merges any local edits over it.
                    actions.applyRemoteNotebookContent(
                        buildMarkdownNotebookContent(nextMarkdown, getMarkdownNotebookNodeId(notebook.content)),
                        event.version
                    )
                    return
                }
            }
            // Version gap, diff-less ping, or a diff that doesn't fit our base: full reload.
            if (isMarkdownNotebookContent(notebook.content)) {
                posthog.capture('notebook markdown full reload', {
                    short_id: notebook.short_id,
                    reason: !event.diff
                        ? 'missing_diff'
                        : event.version !== notebook.version + 1
                          ? 'version_gap'
                          : 'diff_mismatch',
                })
            }
            actions.loadNotebook()
        },
        processPendingMarkdownStreamEvents: () => {
            const pending: MarkdownStreamEvent[] = cache.pendingMarkdownStreamEvents ?? []
            if (!pending.length) {
                return
            }
            cache.pendingMarkdownStreamEvents = []
            pending.sort((a, b) => a.version - b.version).forEach((event) => actions.handleMarkdownStreamEvent(event))
        },
        reportMarkdownMergeConflicts: ({ conflicts }) => {
            if (!conflicts.length) {
                return
            }
            posthog.capture('notebook markdown merge conflict', {
                short_id: values.notebook?.short_id,
                conflict_count: conflicts.length,
            })
            lemonToast.warning(
                conflicts.length === 1
                    ? "Your edit and a collaborator's edit to the same block couldn't be merged — your version is showing."
                    : `Your edits and a collaborator's edits to ${conflicts.length} blocks couldn't be merged — your versions are showing.`,
                {
                    toastId: `notebook-merge-conflict-${values.shortId}`,
                    button: {
                        label: 'Review',
                        action: () => {
                            posthog.capture('notebook markdown merge conflict reviewed', {
                                short_id: values.notebook?.short_id,
                                conflict_count: conflicts.length,
                            })
                            actions.showMarkdownMergeConflictDetails(conflicts)
                        },
                    },
                }
            )
        },
        insertAfterLastNode: async ({ content }) => {
            await runWhenEditorIsReady(
                () =>
                    (values.isLocalOnly || !!values.notebook) &&
                    (!!values.editor || isMarkdownNotebookContent(values.content)),
                () => {
                    const markdownContent = appendContentToMarkdownNotebook(values.content, content)
                    if (markdownContent) {
                        actions.setLocalContent(markdownContent)
                        return
                    }

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
                () =>
                    (values.isLocalOnly || !!values.notebook) &&
                    (!!values.editor || isMarkdownNotebookContent(values.content)),
                () => {
                    const markdownContent = appendContentToMarkdownNotebook(values.content, content)
                    if (markdownContent) {
                        actions.setLocalContent(markdownContent)
                        return
                    }

                    const endPosition = values.editor?.getEndPosition() || 0
                    values.editor?.pasteContent(endPosition, content)
                }
            )
        },
        insertAfterLastNodeOfType: async ({ content, nodeType, knownStartingPosition }) => {
            await runWhenEditorIsReady(
                () =>
                    (values.isLocalOnly || !!values.notebook) &&
                    (!!values.editor || isMarkdownNotebookContent(values.content)),
                () => {
                    // Markdown notebooks have no node positions — append at the end instead.
                    const markdownContent = appendContentToMarkdownNotebook(values.content, content)
                    if (markdownContent) {
                        actions.setLocalContent(markdownContent)
                        return
                    }

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

            if (isMarkdownNotebookContent(values.content)) {
                actions.setLocalContent(
                    appendMarkdownNotebookBlock(
                        values.content,
                        serializeMarkdownNotebookComponent('Query', {
                            hideFilters: true,
                            query: {
                                kind: NodeKind.SavedInsightNode,
                                shortId: insightShortId,
                            },
                        })
                    )
                )
                lemonToast.success('Insight added to notebook')
                return
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
        addExperimentToNotebook: async ({ experimentId, insertionPosition }) => {
            const content = {
                type: NotebookNodeType.Experiment,
                attrs: {
                    id: experimentId,
                },
            }

            if (isMarkdownNotebookContent(values.content)) {
                actions.setLocalContent(
                    appendMarkdownNotebookBlock(
                        values.content,
                        serializeMarkdownNotebookComponent('Experiment', { id: experimentId })
                    )
                )
                lemonToast.success('Experiment added to notebook')
                return
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
                lemonToast.success('Experiment added to notebook')
            } else {
                lemonToast.warning('Could not add experiment to notebook')
            }
        },
        handleMarkdownEditorChange: ({ markdown }) => {
            if (values.markdownEditorInteractionActive) {
                actions.setMarkdownEditorBuffer(markdown)
                actions.setMarkdownEditorDraft(markdown)
                return
            }

            if (markdown === values.markdownEditorMarkdown) {
                return
            }

            actions.setLocalContent(buildMarkdownNotebookContent(markdown, values.markdownEditorNodeId))
        },

        setMarkdownEditorInteractionActive: ({ active }) => {
            if (active) {
                if (values.markdownEditorDraft === null) {
                    actions.setMarkdownEditorDraft(values.markdownEditorMarkdown)
                }
                actions.setAutosavePaused(true)
                return
            }

            const bufferedMarkdown = values.markdownEditorBuffer
            actions.setMarkdownEditorBuffer(null)
            if (bufferedMarkdown !== null && bufferedMarkdown !== values.markdownEditorMarkdown) {
                actions.setLocalContent(buildMarkdownNotebookContent(bufferedMarkdown, values.markdownEditorNodeId))
            }
            actions.setMarkdownEditorDraft(null)
            actions.setAutosavePaused(false)
        },

        applyNotebookArtifactMarkdown: ({ content, mode }) => {
            const artifactMarkdown = notebookArtifactContentToMarkdown(content)
            if (!artifactMarkdown.trim()) {
                return
            }

            const currentMarkdown = values.markdownEditorValue
            const nextMarkdown =
                mode === 'insert-after-response'
                    ? [currentMarkdown, artifactMarkdown].filter((block) => block.trim()).join('\n\n')
                    : artifactMarkdown
            if (nextMarkdown === currentMarkdown) {
                return
            }

            actions.setMarkdownEditorBuffer(null)
            actions.setMarkdownEditorDraft(null)
            actions.setAutosavePaused(false)
            actions.setLocalContent(buildMarkdownNotebookContent(nextMarkdown, values.markdownEditorNodeId))
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

            if (values.markdownRealtimeEnabled) {
                // Debounce between keystrokes, but never let continuous typing starve the save:
                // past MARKDOWN_SYNC_MAX_DELAY of pending edits, save immediately so collaborators
                // typing in the same block converge at near-realtime cadence.
                cache.firstPendingSyncAt = cache.firstPendingSyncAt ?? Date.now()
                if (Date.now() - cache.firstPendingSyncAt >= MARKDOWN_SYNC_MAX_DELAY) {
                    await breakpoint(1)
                } else {
                    await breakpoint(MARKDOWN_SYNC_DELAY)
                }
                cache.firstPendingSyncAt = null
            } else {
                await breakpoint(SYNC_DELAY)
            }

            if (values.autosavePaused) {
                return
            }

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
                    is_markdown: isMarkdownNotebookContent(values.content),
                })
            }

            if (!values.isLocalOnly && values.localContent && values.content && !values.notebookLoading) {
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
            if (values.previewContent) {
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

        saveNotebookSuccess: ({ payload }) => {
            // Clear only the saved object; newer edits get a new object. For markdown notebooks a
            // conflict resolution reload also lands here, but then the loaded server content differs
            // from the attempted content — the local draft must survive so the editor can merge and retry.
            const attemptedContent = payload?.notebook.content
            if (
                attemptedContent === values.localContent &&
                (!isMarkdownNotebookContent(attemptedContent) ||
                    objectsEqual(values.notebook?.content, attemptedContent))
            ) {
                actions.clearLocalContent()
            }
            actions.scheduleNotebookRefresh()
            if (values.showHistory) {
                activityLogLogic({ scope: ActivityScope.NOTEBOOK, id: values.shortId }).actions.fetchActivity()
            }
            actions.processPendingMarkdownStreamEvents()
        },
        saveNotebookFailure: () => {
            actions.processPendingMarkdownStreamEvents()
        },
        loadNotebookSuccess: ({ notebook }) => {
            if (
                notebook &&
                isMarkdownNotebookContent(notebook.content) &&
                values.localContent &&
                !isMarkdownNotebookContent(values.localContent)
            ) {
                actions.clearLocalContent()
            }
            actions.scheduleNotebookRefresh()
            actions.maybeLoadComments()
            actions.processPendingMarkdownStreamEvents()
        },
        loadNotebookFailure: () => {
            actions.processPendingMarkdownStreamEvents()
        },

        exportJSON: () => {
            const file = new File(
                [JSON.stringify(values.editor?.getJSON() ?? values.content, null, 2)],
                `${slugify(values.title ?? 'untitled')}.ph-notebook.json`,
                { type: 'application/json' }
            )

            downloadFile(file)
        },
        downloadMarkdown: () => {
            const markdown = getMarkdownNotebookMarkdown(values.content)
            const file = new File([markdown], `${slugify(values.title ?? 'untitled')}.md`, { type: 'text/markdown' })

            downloadFile(file)
        },
        copyMarkdown: async () => {
            await copyToClipboard(getMarkdownNotebookMarkdown(values.content), 'markdown')
        },

        discardLocalChanges: () => {
            posthog.capture('notebook collab conflict resolved', {
                short_id: values.notebook?.short_id,
                choice: 'discard',
            })
            // Reload remounts the editor so it re-initialises with the server's content.
            actions.clearLocalContent()
            window.location.reload()
        },

        rebaseFailed: async ({ localContent, localText }) => {
            // prosemirror-collab couldn't apply a remote step; the modal lets the user copy or discard.
            if (!values.notebook) {
                return
            }
            // Fetch fresh server content for the side-by-side preview of the changes.
            let serverContent: JSONContent = {}
            try {
                const fresh = await api.notebooks.get(values.notebook.short_id, undefined, {})
                serverContent = (fresh.content as JSONContent) ?? {}
            } catch (e) {
                posthog.captureException(e as Error, { action: 'notebook collab fetch server content' })
                lemonToast.warning('Could not load the latest saved version.')
            }
            actions.showCollabConflict({ serverContent, localContent, localText })
        },

        copyUnsavedToNewNotebook: async () => {
            // Save unsaved edits to a fresh notebook, then navigate to it.
            if (!values.notebook || !values.collabConflict) {
                return
            }
            try {
                const sourceTitle = values.notebook.title || 'Untitled'
                const newTitle = `${sourceTitle} (copy)`
                const created = await api.notebooks.create({
                    content: updateContentHeading(values.collabConflict.localContent, newTitle),
                    text_content: values.collabConflict.localText,
                    title: newTitle,
                })
                lemonToast.success('Saved your unsaved changes to a new notebook.')
                posthog.capture('notebook collab conflict resolved', {
                    short_id: values.notebook.short_id,
                    choice: 'copy_to_new',
                })
                actions.dismissCollabConflict()
                actions.clearLocalContent()
                await openNotebook(created.short_id, NotebookTarget.Scene)
            } catch {
                lemonToast.error('Could not copy your changes to a new notebook.')
            }
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

            // Remove any existing refresh timeout
            cache.disposables.dispose('refreshTimeout')

            // When collab or markdown realtime is enabled, SSE handles sync.
            if (values.collabEnabled || values.markdownRealtimeEnabled) {
                return
            }

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
        markdownRealtimeEnabled: (enabled: boolean) => {
            if (enabled) {
                actions.connectMarkdownUpdateStream()
            } else {
                actions.disconnectMarkdownUpdateStream()
            }
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

    beforeUnload((logic) => ({
        enabled: (newLocation?: CombinedLocation) =>
            shouldWarnBeforeLeavingNotebook({
                isLocalOnly: logic.values.isLocalOnly,
                isEditable: logic.values.isEditable,
                syncStatus: logic.values.syncStatus,
                currentPathname: router.values.location.pathname,
                newPathname: newLocation?.pathname,
            }),
        message: 'Leave notebook?\nChanges you made may not be saved.',
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
