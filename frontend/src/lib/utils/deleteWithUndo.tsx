import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { QueryBasedInsightModel } from '~/types'

function objectLabel(object: Record<string, any>): JSX.Element {
    return object.name || <i>{object.derived_name || 'Unnamed'}</i>
}

/**
 * Reports a failed delete and tells the caller whether the object was already gone. A 404 means the
 * delete landed earlier, so echoing the API's "Not found." would tell the user a destructive action
 * did not happen when it did.
 */
function handleDeleteFailure(
    error: any,
    undo: boolean,
    props: { endpoint: string; object: Record<string, any>; callback?: (undo: boolean, object: any) => void }
): boolean {
    const status = error instanceof ApiError ? error.status : undefined
    const alreadyDeleted = !undo && status === 404

    posthog.capture('delete with undo failed', {
        endpoint: props.endpoint,
        status,
        undo,
        already_deleted: alreadyDeleted,
    })

    if (!alreadyDeleted) {
        lemonToast.error(error.detail || error.message || 'Failed to delete')
        return false
    }

    props.callback?.(false, props.object)
    lemonToast.info(
        <>
            <b>{objectLabel(props.object)}</b> was already deleted
        </>
    )
    return true
}

/** Resolves to true when the object is gone from the server, false when the request failed. */
export async function deleteWithUndo<T extends Record<string, any>>({
    undo = false,
    ...props
}: {
    undo?: boolean
    endpoint: string
    object: T
    idField?: keyof T
    callback?: (undo: boolean, object: T) => void
}): Promise<boolean> {
    try {
        await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
            ...props.object,
            deleted: !undo,
        })
        props.callback?.(undo, props.object)
        lemonToast[undo ? 'success' : 'info'](
            <>
                <b>{objectLabel(props.object)}</b> has been {undo ? 'restored' : 'deleted'}
            </>,
            {
                toastId: `delete-item-${props.object.id}-${undo}`,
                button: undo
                    ? undefined
                    : {
                          label: 'Undo',
                          action: () => deleteWithUndo({ undo: true, ...props }),
                      },
            }
        )
        return true
    } catch (error: any) {
        return handleDeleteFailure(error, undo, props)
    }
}

/** Temporary duplicate of the function above that handles saving and restoring insights with filters
 * when given a query based insight */
export async function deleteInsightWithUndo({
    undo = false,
    ...props
}: {
    undo?: boolean
    endpoint: string
    object: QueryBasedInsightModel
    idField?: keyof QueryBasedInsightModel
    callback?: (undo: boolean, object: QueryBasedInsightModel) => void
}): Promise<boolean> {
    const syncTree = (deleted: boolean): void => {
        if (props.object.short_id) {
            if (deleted) {
                deleteFromTree('insight', String(props.object.short_id))
            } else {
                refreshTreeItem('insight', String(props.object.short_id))
            }
        }
    }

    try {
        await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
            ...props.object,
            deleted: !undo,
        })
        props.callback?.(undo, props.object)
        syncTree(!undo)
        lemonToast[undo ? 'success' : 'info'](
            <>
                <b>{objectLabel(props.object)}</b> has been {undo ? 'restored' : 'deleted'}
            </>,
            {
                toastId: `delete-item-${props.object.id}-${undo}`,
                button: undo
                    ? undefined
                    : {
                          label: 'Undo',
                          action: () => deleteInsightWithUndo({ undo: true, ...props }),
                      },
            }
        )
        return true
    } catch (error: any) {
        const alreadyDeleted = handleDeleteFailure(error, undo, props)
        if (alreadyDeleted) {
            syncTree(true)
        }
        return alreadyDeleted
    }
}
