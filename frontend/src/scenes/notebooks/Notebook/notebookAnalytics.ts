import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'

import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'
import { AccessControlLevel, UserType } from '~/types'

import type { NotebookRunStatusResponseApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NotebookType } from '../types'
import type { InlineAICompletion } from './MarkdownNotebookInlineAI'

export type NotebookInlineAIRequestedProperties = {
    conversation_id: string
    notebook_short_id: string | null
    source: MarkdownNotebookAskAIRequest['source']
    prompt_length: number
    has_selection: boolean
}

export type NotebookInlineAIFinishedProperties = NotebookInlineAIRequestedProperties & {
    status: InlineAICompletion['status']
    result_kind: InlineAICompletion['kind']
    has_artifact: boolean
    duration_ms: number | null
}

/**
 * Builds the `notebook inline ai requested` event payload. It carries lengths and flags only, because
 * the prompt and the selected markdown can contain customer data.
 */
export function buildNotebookInlineAIRequestedEvent(
    request: MarkdownNotebookAskAIRequest,
    notebookShortId: string | null
): NotebookInlineAIRequestedProperties {
    return {
        conversation_id: request.conversationId,
        notebook_short_id: notebookShortId,
        source: request.source,
        prompt_length: request.query.length,
        has_selection: !!request.selectedMarkdown,
    }
}

export function buildNotebookInlineAIFinishedEvent(
    request: MarkdownNotebookAskAIRequest,
    completion: InlineAICompletion,
    notebookShortId: string | null,
    startedAtMs: number | undefined,
    finishedAtMs: number
): NotebookInlineAIFinishedProperties {
    return {
        ...buildNotebookInlineAIRequestedEvent(request, notebookShortId),
        status: completion.status,
        result_kind: completion.kind,
        has_artifact: completion.hasArtifact,
        duration_ms: startedAtMs === undefined ? null : Math.max(0, Math.round(finishedAtMs - startedAtMs)),
    }
}

export type NotebookOpenedProperties = {
    short_id: string
    is_creator: boolean
    user_access_level?: AccessControlLevel
    access_source: 'direct' | 'shared_link'
    node_count: number
}

/**
 * Builds the `notebook opened` event payload, or `null` when the loaded notebook is not a real
 * persisted notebook (scratchpad / template) and so should not count as a human open.
 */
export function buildNotebookOpenedEvent(
    notebook: NotebookType | null,
    user: UserType | null,
    isShared: boolean
): NotebookOpenedProperties | null {
    const shortId = notebook?.short_id
    if (!notebook || !shortId || shortId === SCRATCHPAD_NOTEBOOK.short_id || shortId.startsWith('template-')) {
        return null
    }
    return {
        short_id: shortId,
        is_creator: !!user && notebook.created_by?.uuid === user.uuid,
        user_access_level: notebook.user_access_level,
        access_source: isShared ? 'shared_link' : 'direct',
        node_count: notebook.content?.content?.length ?? 0,
    }
}

export type NotebookRunAllStartedProperties = {
    short_id: string
    cell_count: number
}

export type NotebookRunAllFinishedProperties = {
    short_id: string
    cell_count: number
    python_cell_count: number
    completed_count: number
    outcome: string
    duration_ms: number
}

/** No code and no cell content in the properties: a run's payload is counts and an outcome. */
export function buildNotebookRunStartedEvent(
    shortId: string,
    cellCount: number
): ['notebook run all started', NotebookRunAllStartedProperties] {
    return ['notebook run all started', { short_id: shortId, cell_count: cellCount }]
}

export function buildNotebookRunFinishedEvent(
    shortId: string,
    run: NotebookRunStatusResponseApi,
    durationMs: number
): ['notebook run all finished', NotebookRunAllFinishedProperties] {
    return [
        'notebook run all finished',
        {
            short_id: shortId,
            cell_count: run.cell_count,
            python_cell_count: run.cells.filter((cell) => cell.cell_type === 'python').length,
            completed_count: run.cells.filter((cell) => cell.status === 'done').length,
            outcome: run.status,
            duration_ms: durationMs,
        },
    ]
}
