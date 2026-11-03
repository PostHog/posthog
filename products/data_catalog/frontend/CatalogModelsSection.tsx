import { useValues } from 'kea'
import { useCallback } from 'react'

import { urls } from 'scenes/urls'

import { DataWarehouseSavedQuery } from '~/types'

import { modelsSceneLogic } from 'products/data_modeling/frontend/modelsSceneLogic'
import { ViewsTab } from 'products/data_modeling/frontend/ViewsTab'

export function CatalogModelsSection(): JSX.Element {
    const { savedQueryIdToNodeId, suspensionBySavedQueryId } = useValues(modelsSceneLogic)
    const getViewUrl = useCallback(
        (view: Pick<DataWarehouseSavedQuery, 'id'>): string => {
            const nodeId = savedQueryIdToNodeId[view.id]
            return nodeId ? urls.nodeDetail(nodeId) : urls.sqlEditor({ view_id: view.id })
        },
        [savedQueryIdToNodeId]
    )
    return <ViewsTab getViewUrl={getViewUrl} suspensionByViewId={suspensionBySavedQueryId} />
}
