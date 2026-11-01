import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { liveDashboardIds } from 'scenes/dashboard/liveDashboardIds'
import { insightsApi } from 'scenes/insights/utils/api'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { InsightModel } from '~/types'

export async function deleteWithUndo<T extends Record<string, any>>({
    undo = false,
    ...props
}: {
    undo?: boolean
    endpoint: string
    object: T
    idField?: keyof T
    /** The name the toast shows. It defaults to `object.name`, which the request body also sends. */
    label?: string
    /** The request body besides `deleted`. Defaults to the whole `object`. */
    payload?: Record<string, any>
    undoable?: boolean
    /** Runs before the error toast. Return true when it handled the error, which skips the toast. */
    handleError?: (error: any) => boolean
    callback?: (undo: boolean, object: T) => void
    /** Runs when the request fails, so a caller that removed the object from its state before the
     * request can put it back. */
    onError?: (undo: boolean, object: T) => void
}): Promise<void> {
    try {
        // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
        await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
            ...(props.payload ?? props.object),
            deleted: !undo,
        })
        props.callback?.(undo, props.object)
        lemonToast[undo ? 'success' : 'info'](
            <>
                <b>{props.label || props.object.name || <i>{props.object.derived_name || 'Unnamed'}</i>}</b> has been{' '}
                {undo ? 'restored' : 'deleted'}
            </>,
            {
                toastId: `delete-item-${props.object.id}-${undo}`,
                button:
                    undo || props.undoable === false
                        ? undefined
                        : {
                              label: 'Undo',
                              action: () => deleteWithUndo({ undo: true, ...props }),
                          },
            }
        )
    } catch (error: any) {
        if (!props.handleError?.(error)) {
            // Show error toast with the error message from the API
            const errorMessage = error.detail || error.message || 'Failed to delete'
            lemonToast.error(errorMessage)
        }
        props.onError?.(undo, props.object)
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
    object: InsightModel
    idField?: keyof InsightModel
    /** The dashboards an undo puts the insight back on. Defaults to the dashboards its live tiles sit on. */
    dashboardIds?: number[]
    callback?: (undo: boolean, object: InsightModel) => void
}): Promise<void> {
    try {
        const { dashboards: _dashboards, ...insight } = props.object
        // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
        await api.update(`api/${props.endpoint}/${props.object[props.idField || 'id']}`, {
            ...insight,
            deleted: !undo,
        })
        let dashboardsNotRestored = 0
        if (undo) {
            // Each add restores a tile the delete hid. One refused dashboard must not skip the updates below.
            const placements = await Promise.allSettled(
                (props.dashboardIds ?? liveDashboardIds(props.object.dashboard_tiles)).map((dashboardId) =>
                    insightsApi.addToDashboard(props.object.id, dashboardId)
                )
            )
            dashboardsNotRestored = placements.filter((placement) => placement.status === 'rejected').length
        }
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
        if (dashboardsNotRestored > 0) {
            lemonToast.warning(
                `The insight is back, but it couldn't be put back on ${dashboardsNotRestored} of its dashboards. Add it to them from the insight page.`
            )
        }
    } catch (error: any) {
        // Show error toast with the error message from the API
        const errorMessage = error.detail || error.message || 'Failed to delete'
        lemonToast.error(errorMessage)
    }
}
