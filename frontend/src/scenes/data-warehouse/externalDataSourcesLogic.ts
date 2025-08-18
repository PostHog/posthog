import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

export interface UnifiedRecentActivity {
    id: string
    name: string | null
    type: string
    status: string
    created_at: string
    rows: number
    finished_at?: string | null
    latest_error?: string | null
    schema_id?: string
    source_id?: string
    workflow_run_id?: string
}

export interface DashboardDataSource {
    id: string
    name: string
    status: string | null
    lastSync: string | null
    rowCount: number | null
    url: string
}

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({
        abortAnyRunningQuery: true,
        loadTotalRowsProcessed: true,
        loadRecentActivity: true,
    }),
    loaders(({ cache, values, actions }) => ({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadSources: async (_, breakpoint) => {
                    await breakpoint(300)
                    actions.abortAnyRunningQuery()

                    cache.abortController = new AbortController()
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }
                    const res = await api.externalDataSources.list(methodOptions)
                    breakpoint()

                    cache.abortController = null

                    return res
                },
                updateSource: async (source: ExternalDataSource) => {
                    const updatedSource = await api.externalDataSources.update(source.id, source)
                    return {
                        ...values.dataWarehouseSources,
                        results:
                            values.dataWarehouseSources?.results.map((s: ExternalDataSource) =>
                                s.id === updatedSource.id ? updatedSource : s
                            ) || [],
                    }
                },
            },
        ],
        totalRowsProcessed: [
            0 as number,
            {
                loadTotalRowsProcessed: async () => {
                    try {
                        const response = await api.dataWarehouse.total_rows_stats()
                        return response.total_rows || 0
                    } catch (error) {
                        posthog.captureException(error)
                        return 0
                    }
                },
            },
        ],
        recentActivity: [
            [] as UnifiedRecentActivity[],
            {
                loadRecentActivity: async () => {
                    try {
                        const response = await api.dataWarehouse.recentActivity()
                        return response.results || []
                    } catch (error) {
                        posthog.captureException(error)
                        return []
                    }
                },
            },
        ],
    })),
    reducers(({ cache }) => ({
        dataWarehouseSourcesLoading: [
            false as boolean,
            {
                loadSources: () => true,
                loadSourcesFailure: () => cache.abortController !== null,
                loadSourcesSuccess: () => cache.abortController !== null,
            },
        ],
    })),
    listeners(({ cache }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
        actions.loadTotalRowsProcessed()
        actions.loadRecentActivity()
    }),
])
