import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { ActionType } from '~/types'

import type { ActionReferenceApi } from '../generated/api.schemas'

/**
 * Delete an action, warning first if it has references.
 * Fetches references on the fly so it works from both the list and detail pages.
 */
export async function deleteActionWithWarning(action: ActionType, callback: (undo: boolean) => void): Promise<void> {
    let references: ActionReferenceApi[] = []
    try {
        // nosemgrep: prefer-codegen-api
        references = await api.get(`api/projects/@current/actions/${action.id}/references`)
    } catch {
        // If we can't fetch references, proceed with delete anyway
    }

    const performDelete = async (): Promise<void> => {
        await deleteWithUndo({
            endpoint: api.actions.determineDeleteEndpoint(),
            object: action,
            callback,
        })
    }

    if (references.length > 0) {
        LemonDialog.open({
            title: 'This action is used by other resources',
            description: (
                <>
                    This action is referenced by <strong>{references.length}</strong> resource
                    {references.length === 1 ? '' : 's'}. Deleting it may break them.
                </>
            ),
            primaryButton: {
                children: 'Delete anyway',
                status: 'danger',
                onClick: performDelete,
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    } else {
        await performDelete()
    }
}
