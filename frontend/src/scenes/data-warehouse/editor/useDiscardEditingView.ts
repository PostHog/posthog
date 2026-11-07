import { useActions, useValues } from 'kea'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

interface DiscardEditingView {
    disabledReason: string | undefined
    discard: () => void
}

/** Discard state for the view open in the editor. Call it below the SQLEditor bindings. */
export function useDiscardEditingView(): DiscardEditingView {
    const { hasEditorChanges } = useValues(sqlEditorLogic)
    const { discardChanges } = useActions(sqlEditorLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

    const disabledReason = updatingDataWarehouseSavedQuery
        ? 'Wait for the current operation to finish'
        : !hasEditorChanges
          ? 'No changes to discard'
          : undefined

    return { disabledReason, discard: discardChanges }
}
