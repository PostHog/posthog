import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { useUpdateEditingView } from 'scenes/data-warehouse/editor/useUpdateEditingView'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailQueryEditorSync({ id }: { id: string }): null {
    const { disabledReason, loading, isMaterializedView } = useUpdateEditingView()
    const { hasEditorChanges } = useValues(sqlEditorLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { setQueryEditorState } = useActions(nodeDetailSceneLogic({ id }))

    const discardDisabledReason = updatingDataWarehouseSavedQuery
        ? 'Wait for the current operation to finish'
        : !hasEditorChanges
          ? 'No changes to discard'
          : undefined

    useEffect(() => {
        setQueryEditorState({
            updateDisabledReason: disabledReason,
            updateLoading: loading,
            discardDisabledReason,
            isMaterializedView,
        })
    }, [disabledReason, loading, discardDisabledReason, isMaterializedView, setQueryEditorState])

    useOnMountEffect(() => () => setQueryEditorState(null))

    return null
}
