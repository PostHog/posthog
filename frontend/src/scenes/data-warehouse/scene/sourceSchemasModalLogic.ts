import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { dataWarehouseManagedWarehouseSourceSchemasRetrieve } from 'products/data_warehouse/frontend/generated/api'
import type { ManagedWarehouseSourceTableStatusApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { sourceSchemasModalLogicType } from './sourceSchemasModalLogicType'

export interface ActiveSource {
    sourceId: string
    sourceName: string
}

export const sourceSchemasModalLogic = kea<sourceSchemasModalLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'sourceSchemasModalLogic']),
    actions({
        closeSourceSchemasModal: true,
    }),
    loaders({
        sourceSchemas: [
            [] as ManagedWarehouseSourceTableStatusApi[],
            {
                loadSourceSchemas: async ({ sourceId }: ActiveSource) => {
                    const response = await dataWarehouseManagedWarehouseSourceSchemasRetrieve(
                        String(teamLogic.values.currentTeamId),
                        { source_id: sourceId }
                    )
                    return response.schemas
                },
            },
        ],
    }),
    reducers({
        // Doubles as the modal's open/closed state: isOpen={!!activeSource}. Set by the same
        // action that triggers the fetch, so there's no separate "open" step to keep in sync.
        activeSource: [
            null as ActiveSource | null,
            {
                loadSourceSchemas: (_, source) => source,
                closeSourceSchemasModal: () => null,
            },
        ],
    }),
])
