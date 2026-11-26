import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { ActionType } from '~/types'

import { actionsReferencesList } from '../generated/api'
import type { ActionReferenceApi } from '../generated/api.schemas'

/** Asks the person to confirm deleting an action that other resources reference, and calls `performDelete` if they do. */
export type ConfirmReferencedActionDelete = (referenceCount: number, performDelete: () => Promise<void>) => void

function confirmWithLemonDialog(referenceCount: number, performDelete: () => Promise<void>): void {
    LemonDialog.open({
        title: 'This action is used by other resources',
        description: (
            <>
                This action is referenced by <strong>{referenceCount}</strong> resource
                {referenceCount === 1 ? '' : 's'}. Deleting it may break them.
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
}

/**
 * Delete an action, warning first if it has references.
 * Fetches references on the fly so it works from both the list and detail pages.
 */
export async function deleteActionWithWarning(
    projectId: number,
    action: ActionType,
    callback: (undo: boolean) => void,
    confirmDelete: ConfirmReferencedActionDelete = confirmWithLemonDialog
): Promise<void> {
    let references: ActionReferenceApi[] = []
    try {
        references = await actionsReferencesList(String(projectId), action.id)
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
        confirmDelete(references.length, performDelete)
    } else {
        await performDelete()
    }
}
