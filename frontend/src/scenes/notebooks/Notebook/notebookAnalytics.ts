import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'
import { AccessControlLevel, UserType } from '~/types'

import type { NotebookRunStatusResponseApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NotebookType } from '../types'

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
