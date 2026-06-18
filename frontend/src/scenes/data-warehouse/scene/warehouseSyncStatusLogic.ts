import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { dataWarehouseWarehouseSyncStatusRetrieve } from 'products/data_warehouse/frontend/generated/api'
import type { WarehouseSyncStatusApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { warehouseSyncStatusLogicType } from './warehouseSyncStatusLogicType'

const currentProjectId = (): string => String(teamLogic.values.currentTeamId)

export const warehouseSyncStatusLogic = kea<warehouseSyncStatusLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'warehouseSyncStatusLogic']),
    loaders({
        syncStatus: [
            null as WarehouseSyncStatusApi | null,
            {
                loadSyncStatus: async (): Promise<WarehouseSyncStatusApi | null> => {
                    try {
                        return await dataWarehouseWarehouseSyncStatusRetrieve(currentProjectId())
                    } catch (e: any) {
                        if (e.status === 404) {
                            return null
                        }
                        throw e
                    }
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSyncStatus()
    }),
])
