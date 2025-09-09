import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { QueryBasedInsightModel } from '~/types'

export async function deleteWithUndo<T extends Record<string, any>>({
    undo = false,
    ...props
}: {
    undo?: boolean
    endpoint: string
    object: T
    idField?: keyof T
    callback?: (undo: boolean, object: T) => void
}): Promise<void> {
    try {
        await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
            ...props.object,
            deleted: !undo,
        })
        props.callback?.(undo, props.object)
        lemonToast[undo ? 'success' : 'info'](
            <>
                <b>{props.object.name || <i>{props.object.derived_name || 'Unnamed'}</i>}</b> has been{' '}
                {undo ? 'restored' : 'deleted'}
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
    } catch (error: any) {
        // Show error toast with the error message from the API
        const errorMessage = error.detail || error.message || 'Failed to delete'
        lemonToast.error(errorMessage)
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
}): Promise<void> {
    try {
        await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
            ...props.object,
            deleted: !undo,
        })
        props.callback?.(undo, props.object)
        if (props.object.short_id) {
            if (undo) {
                refreshTreeItem('insight', String(props.object.short_id))
            } else {
                deleteFromTree('insight', String(props.object.short_id))
            }
        }
        lemonToast[undo ? 'success' : 'info'](
            <>
                <b>{props.object.name || <i>{props.object.derived_name || 'Unnamed'}</i>}</b> has been{' '}
                {undo ? 'restored' : 'deleted'}
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
    } catch (error: any) {
        // Show error toast with the error message from the API
        const errorMessage = error.detail || error.message || 'Failed to delete'
        lemonToast.error(errorMessage)
    }
}
