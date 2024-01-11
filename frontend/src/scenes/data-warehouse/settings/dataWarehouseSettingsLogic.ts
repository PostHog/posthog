import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, ExternalDataSourceSchema, ExternalDataStripeSource } from '~/types'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'

const REFRESH_INTERVAL = 10000

export interface DataWarehouseSource {}

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    actions({
        deleteSource: (source: ExternalDataStripeSource) => ({ source }),
        reloadSource: (source: ExternalDataStripeSource) => ({ source }),
        loadingFinished: (source: ExternalDataStripeSource) => ({ source }),
        updateSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
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
            try {
                await api.externalDataSources.reload(source.id)
                actions.loadSources()
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant refresh source at this time')
                }
            }
            actions.loadingFinished(source)
        },
        updateSchema: async ({ schema }) => {
            await api.externalDataSchemas.update(schema.id, schema)
            actions.loadSources()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
