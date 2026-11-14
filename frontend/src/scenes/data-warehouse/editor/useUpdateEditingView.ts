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
        editingView,
        hasEditorChanges,
        isMultiQuery,
        saveAsViewDisabledReason,
        queryInput,
        sourceQuery,
        isSourceQueryLastRun,
    } = useValues(sqlEditorLogic)
    const { updateEditingView } = useActions(sqlEditorLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

    const { response, responseError, responseLoading } = useValues(dataNodeLogic)

    const isMaterializedView = editingView?.is_materialized === true

    const { disabledReason, loading } = useMemo((): { disabledReason: string | undefined; loading: boolean } => {
        if (updatingDataWarehouseSavedQuery) {
            return { disabledReason: 'Saving...', loading: true }
        }

        if (saveAsViewDisabledReason) {
            return { disabledReason: saveAsViewDisabledReason, loading: false }
        }

        if (isMultiQuery) {
            return {
                disabledReason: 'Views must be a single query — remove extra statements to update',
                loading: false,
            }
        }

        if (!queryInput?.trim()) {
            return { disabledReason: 'Write a SQL query before saving', loading: false }
        }

        if (
            sourceQuery.source.executionTarget === 'managed_trino' &&
            (!isSourceQueryLastRun || !response || responseError || responseLoading)
        ) {
            return {
                disabledReason: 'Run the latest query successfully to determine the view’s columns',
                loading: responseLoading,
            }
        }

        if (!hasEditorChanges) {
            return { disabledReason: 'No changes to save', loading: false }
        }

        return { disabledReason: undefined, loading: false }
    }, [
        updatingDataWarehouseSavedQuery,
        hasEditorChanges,
        isMultiQuery,
        saveAsViewDisabledReason,
        queryInput,
        sourceQuery,
        isSourceQueryLastRun,
        response,
        responseError,
        responseLoading,
    ])

    return { disabledReason, loading, isMaterializedView, update: updateEditingView }
}
