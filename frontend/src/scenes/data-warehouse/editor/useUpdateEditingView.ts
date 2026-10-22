import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

interface UpdateEditingView {
    disabledReason: string | undefined
    loading: boolean
    isMaterializedView: boolean
    update: () => void
}

/** Update state for the view open in the editor. Call it below the SQLEditor bindings. */
export function useUpdateEditingView(): UpdateEditingView {
    const {
        queryInput,
        editingView,
        sourceQuery,
        changesToSave,
        inProgressViewEdits,
        isSourceQueryLastRun,
        isMultiQuery,
    } = useValues(sqlEditorLogic)
    const { reviewViewUpdate } = useActions(sqlEditorLogic)
    const { response, responseError, responseLoading } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

    const isMaterializedView = editingView?.is_materialized === true

    const { disabledReason, loading } = useMemo((): { disabledReason: string | undefined; loading: boolean } => {
        if (updatingDataWarehouseSavedQuery) {
            return { disabledReason: 'Saving...', loading: true }
        }

        if (isMultiQuery) {
            return {
                disabledReason: 'Views must be a single query — remove extra statements to update',
                loading: false,
            }
        }

        if (!changesToSave) {
            return { disabledReason: 'No changes to save', loading: false }
        }

        // Require the current (edited) query to have been run successfully before updating — a stale
        // response from a previous run must not enable the button after further edits.
        if (!isSourceQueryLastRun) {
            return { disabledReason: 'Run the latest query before updating the view', loading: false }
        }

        if (responseLoading) {
            return { disabledReason: 'Running query...', loading: true }
        }

        if (responseError || !response) {
            return { disabledReason: 'Run the query successfully before updating the view', loading: false }
        }

        return { disabledReason: undefined, loading: false }
    }, [
        updatingDataWarehouseSavedQuery,
        changesToSave,
        isSourceQueryLastRun,
        responseLoading,
        responseError,
        response,
        isMultiQuery,
    ])

    const update = (): void => {
        if (!editingView) {
            return
        }
        reviewViewUpdate({
            id: editingView.id,
            query: {
                ...sourceQuery.source,
                query: queryInput ?? '',
            },
            types: response && 'types' in response ? (response?.types ?? []) : [],
            shouldRematerialize: isMaterializedView,
            edited_history_id: inProgressViewEdits[editingView.id],
        })
    }

    return { disabledReason, loading, isMaterializedView, update }
}
