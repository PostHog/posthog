import { kea, path } from 'kea'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'
import { loaders } from 'kea-loaders'
import { PaginatedResponse } from 'lib/api'

export interface DataWarehouseSource {}

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    loaders({
        dataWarehouseSources: [
            null as PaginatedResponse<DataWarehouseSource> | null,
            {
                loadSources: async () => {
                    return null
                },
            },
        ],
    }),
])
