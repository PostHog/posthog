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
