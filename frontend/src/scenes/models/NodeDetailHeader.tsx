import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { NodeKind } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery } from '~/types'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

function SaveDiscardActions({
    id,
    savedQuery,
}: {
    id: string
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element | null {
    const sqlEditorTabId = useMemo(() => `node-detail-query-${id}`, [id])
    const { queryInput } = useValues(sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded }))
    const { setQueryInput, updateView } = useActions(
        sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded })
    )
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)

    const queryString = savedQuery?.query?.query ?? ''
    const hasChanges = !!queryInput && queryInput !== queryString

    if (!hasChanges) {
        return null
    }

    const handleSave = (): void => {
        if (queryInput) {
            updateView({
                id: savedQuery.id,
                query: { kind: NodeKind.HogQLQuery, query: queryInput },
                types: [],
            })
        }
    }

    return (
        <>
            <LemonButton type="secondary" onClick={() => setQueryInput(queryString)} size="small">
                Discard
            </LemonButton>
            <LemonButton type="primary" onClick={handleSave} loading={updatingDataWarehouseSavedQuery} size="small">
                Save
            </LemonButton>
        </>
    )
}

export function NodeDetailHeader({ id }: { id: string }): JSX.Element {
    const { node, nodeLoading, savedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const { updateNodeDescription } = useActions(nodeDetailSceneLogic({ id }))

    return (
        <SceneTitleSection
            name={node?.name}
            description={node?.description}
            resourceType={{ type: 'sql_editor' }}
            canEdit
            onDescriptionChange={(description) => updateNodeDescription(description)}
            isLoading={nodeLoading && !node}
            renameDebounceMs={500}
            saveOnBlur
            actions={
                savedQuery && node?.type !== 'table' ? (
                    <SaveDiscardActions id={id} savedQuery={savedQuery} />
                ) : undefined
            }
        />
    )
}
