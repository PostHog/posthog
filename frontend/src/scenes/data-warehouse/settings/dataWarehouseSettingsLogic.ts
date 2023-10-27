import { afterMount, kea, path, selectors } from 'kea'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { ExternalDataStripeSource, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'

export interface DataWarehouseSource {}

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    loaders({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataStripeSource> | null,
            {
                loadSources: async () => {
                    return api.externalDataSources.list()
                },
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: `Data Warehouse`,
                    path: urls.dataWarehouseExternal(),
                },
                {
                    name: 'Data Warehouse Settings',
                    path: urls.dataWarehouseSettings(),
                },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
