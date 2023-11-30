import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, ExternalDataStripeSource } from '~/types'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'

const REFRESH_INTERVAL = 5000

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
    listeners(({ actions, cache }) => ({
        loadSourcesSuccess: () => {
            clearTimeout(cache.refreshTimeout)

            cache.refreshTimeout = setTimeout(() => {
                actions.loadSources()
            }, REFRESH_INTERVAL)
        },
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
