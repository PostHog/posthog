import { afterMount, kea, path } from 'kea'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { AirbyteStripeResource } from '~/types'

export interface DataWarehouseSource {}

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    loaders({
        dataWarehouseSources: [
            null as PaginatedResponse<AirbyteStripeResource> | null,
            {
                loadSources: async () => {
                    return api.airbyteResources.list()
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
