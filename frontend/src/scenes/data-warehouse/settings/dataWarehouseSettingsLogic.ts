import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { ExternalDataStripeSource, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { Scene } from 'scenes/sceneTypes'

export interface DataWarehouseSource {}

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    actions({
        deleteSource: (source: ExternalDataStripeSource) => ({ source }),
        reloadSource: (source: ExternalDataStripeSource) => ({ source }),
        loadingFinished: (source: ExternalDataStripeSource) => ({ source }),
    }),
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
    reducers({
        sourceReloadingById: [
            {} as Record<string, boolean>,
            {
                reloadSource: (state, { source }) => ({
                    ...state,
                    [source.id]: true,
                }),
                deleteSource: (state, { source }) => ({
                    ...state,
                    [source.id]: true,
                }),
                loadingFinished: (state, { source }) => ({
                    ...state,
                    [source.id]: false,
                }),
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.DataWarehouse,
                    name: `Data Warehouse`,
                    path: urls.dataWarehouseExternal(),
                },
                {
                    key: Scene.DataWarehouseSettings,
                    name: 'Data Warehouse Settings',
                    path: urls.dataWarehouseSettings(),
                },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        deleteSource: async ({ source }) => {
            await api.externalDataSources.delete(source.id)
            actions.loadSources()
            actions.loadingFinished(source)
        },
        reloadSource: async ({ source }) => {
            await api.externalDataSources.reload(source.id)
            actions.loadSources()
            actions.loadingFinished(source)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
