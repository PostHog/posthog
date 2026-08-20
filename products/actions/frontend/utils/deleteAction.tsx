import api, { ApiConfig } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { ActionType } from '~/types'

import { actionsReferencesList } from '../generated/api'
import type { ActionReferenceApi } from '../generated/api.schemas'

/**
 * Delete an action, warning first if it has references.
 * Fetches references on the fly so it works from both the list and detail pages.
 */
export async function deleteActionWithWarning(action: ActionType, callback: (undo: boolean) => void): Promise<void> {
    let references: ActionReferenceApi[] = []
    let referencesUnknown = false
    try {
        // Scope to the project in the route, not the server's active project, so a cross-project
        // action resolves instead of 404ing on a hardcoded "@current".
        references = await actionsReferencesList(String(ApiConfig.getCurrentProjectId()), action.id)
    } catch (error: any) {
        // A missing or forbidden action has no references to warn about. Any other failure means we
        // could not verify, so we say so rather than presenting the action as safe to delete.
        if (error?.status !== 404 && error?.status !== 403) {
            referencesUnknown = true
        }
    }

    const performDelete = async (): Promise<void> => {
        await deleteWithUndo({
            endpoint: api.actions.determineDeleteEndpoint(),
            object: action,
            callback,
        })
    }

    const warning =
        references.length > 0
            ? {
                  title: 'This action is used by other resources',
                  description: (
                      <>
                          This action is referenced by <strong>{references.length}</strong> resource
                          {references.length === 1 ? '' : 's'}. Deleting it may break them.
                      </>
                  ),
              }
            : referencesUnknown
              ? {
                    title: 'Could not check where this action is used',
                    description: (
                        <>We could not load the resources that reference this action. Deleting it may break them.</>
                    ),
                }
              : null

    if (!warning) {
        await performDelete()
        return
    }

    LemonDialog.open({
        ...warning,
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
