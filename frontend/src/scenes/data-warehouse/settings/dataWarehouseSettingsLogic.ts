import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { ExternalDataSource, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { streamModalLogic } from './streamModalLogic'
import { Scene } from 'scenes/sceneTypes'

export interface DataWarehouseSource {}

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    actions({
        deleteSource: (source: ExternalDataSource) => ({ source }),
        reloadSource: (source: ExternalDataSource) => ({ source }),
        loadingFinished: (source: ExternalDataSource) => ({ source }),
    }),
    connect({
        values: [streamModalLogic, ['isStreamModalVisible']],
        actions: [streamModalLogic, ['toggleStreamModal']],
    }),
    loaders({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
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
