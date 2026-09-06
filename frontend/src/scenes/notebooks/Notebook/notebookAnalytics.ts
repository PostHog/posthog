import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'
import { AccessControlLevel, UserType } from '~/types'

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

// Analytics contract — frozen wire strings. Do not rename: breakdowns of `react_framerate` and
// `$web_vitals` by notebook size depend on these exact keys.
export const NOTEBOOK_SIZE_PROPERTY_KEYS = [
    'notebook_short_id',
    'notebook_cell_count',
    'notebook_code_cell_count',
    'notebook_char_length',
] as const

export type NotebookSizeProperties = {
    notebook_short_id: string
    notebook_cell_count: number
    notebook_code_cell_count: number
    notebook_char_length: number
}

/**
 * Builds the notebook-size super-properties, or `null` when the notebook is not a real persisted
 * notebook (scratchpad / template) or is an anonymous shared view. Registering these while a
 * notebook is open lets the existing `react_framerate` and `$web_vitals` events be sliced by
 * notebook size, so we can tell whether responsiveness degrades as a notebook grows.
 */
export function buildNotebookSizeProperties(
    notebook: NotebookType | null,
    isShared: boolean,
    sizes: { cellCount: number; codeCellCount: number; charLength: number }
): NotebookSizeProperties | null {
    const shortId = notebook?.short_id
    if (
        !notebook ||
        !shortId ||
        shortId === SCRATCHPAD_NOTEBOOK.short_id ||
        shortId.startsWith('template-') ||
        isShared
    ) {
        return null
    }
    return {
        notebook_short_id: shortId,
        notebook_cell_count: sizes.cellCount,
        notebook_code_cell_count: sizes.codeCellCount,
        notebook_char_length: sizes.charLength,
    }
}
