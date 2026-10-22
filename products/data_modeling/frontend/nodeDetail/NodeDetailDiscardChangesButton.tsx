import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

export function NodeDetailDiscardChangesButton(): JSX.Element {
    const { hasEditorChanges } = useValues(sqlEditorLogic)
    const { discardChanges } = useActions(sqlEditorLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => discardChanges()}
            disabledReason={
                updatingDataWarehouseSavedQuery
                    ? 'Wait for the current operation to finish'
                    : !hasEditorChanges
                      ? 'No changes to discard'
                      : undefined
            }
            data-attr="node-detail-discard-changes"
        >
            Discard changes
        </LemonButton>
    )
}
