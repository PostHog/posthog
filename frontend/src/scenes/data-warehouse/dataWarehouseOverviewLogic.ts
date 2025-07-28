import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { lemonToast } from '@posthog/lemon-ui'
import api, { PaginatedResponse } from 'lib/api'

import { ExternalDataSource } from '~/types'
import type { dataWarehouseOverviewLogicType } from './dataWarehouseOverviewLogicType'

export const dataWarehouseOverviewLogic = kea<dataWarehouseOverviewLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseOverviewLogic']),

    actions({
        updateDataSource: (dataSource: ExternalDataSource) => ({ dataSource }),
        syncDataSource: (id: string) => ({ id }),
        resyncDataSource: (id: string) => ({ id }),
        deleteDataSource: (id: string) => ({ id }),
    }),

    loaders({
        dataSourcesResponse: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadDataSources: async () => {
                    const response = await api.externalDataSources.list()
                    return response
                },
            },
        ],
    }),

    reducers({}),

    selectors({
        dataSources: [
            (s) => [s.dataSourcesResponse],
            (dataSourcesResponse): ExternalDataSource[] => dataSourcesResponse?.results || [],
        ],
        dataSourcesLoading: [(s) => [s.dataSourcesResponseLoading], (loading): boolean => loading],
        activeDataSources: [
            (s) => [s.dataSources],
            (dataSources) =>
                dataSources.filter((ds) =>
                    ds.schemas.some((schema) => schema.should_sync && schema.status === 'Completed')
                ),
        ],
        failedDataSources: [
            (s) => [s.dataSources],
            (dataSources) => dataSources.filter((ds) => ds.schemas.some((schema) => schema.status === 'Failed')),
        ],
        totalRowCount: [
            (s) => [s.dataSources],
            (dataSources) =>
                dataSources.reduce(
                    (total, ds) =>
                        total +
                        ds.schemas.reduce((schemaTotal, schema) => schemaTotal + (schema.table?.row_count || 0), 0),
                    0
                ),
        ],
    }),

    listeners(({ actions, values }) => ({
        syncDataSource: async ({ id }) => {
            const dataSource = values.dataSources.find((ds) => ds.id === id)
            if (!dataSource) {
                return
            }

            try {
                await api.externalDataSources.reload(id)
                lemonToast.success(`Started sync for ${dataSource.source_id}`)
                setTimeout(() => actions.loadDataSources(), 1000)
            } catch {
                lemonToast.error('Failed to start sync')
                actions.loadDataSources()
            }
        },

        resyncDataSource: async ({ id }) => {
            const dataSource = values.dataSources.find((ds) => ds.id === id)
            if (!dataSource) {
                return
            }

            try {
                await api.externalDataSources.reload(id)
                lemonToast.success(`Started full resync for ${dataSource.source_id}`)
                setTimeout(() => actions.loadDataSources(), 1000)
            } catch {
                lemonToast.error('Failed to start resync')
                actions.loadDataSources()
            }
        },

        deleteDataSource: async ({ id }) => {
            const dataSource = values.dataSources.find((ds) => ds.id === id)
            if (!dataSource) {
                return
            }

            try {
                await api.externalDataSources.delete(id)
                lemonToast.success(`Deleted ${dataSource.source_id}`)
            } catch {
                lemonToast.error('Failed to delete data source')
                actions.loadDataSources()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadDataSources()
    }),
])
