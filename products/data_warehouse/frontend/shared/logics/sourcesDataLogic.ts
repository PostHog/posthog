import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { ExternalDataSource, ExternalDataSourceRevenueAnalyticsConfig } from '~/types'

import type { sourcesDataLogicType } from './sourcesDataLogicType'

export const sourcesDataLogic = kea<sourcesDataLogicType>([
    path(['products', 'dataWarehouse', 'sourcesDataLogic']),
    actions({
        abortAnyRunningQuery: true,
        loadSources: true,
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
                    try {
                        const res = await api.externalDataSources.list(methodOptions)
                        breakpoint()

                        cache.abortController = null

                        return res
                    } catch (error: any) {
                        // On 403, return empty result instead of failing - user doesn't have access
                        if (error.status === 403) {
                            cache.abortController = null
                            return { results: [], count: 0, next: null, previous: null }
                        }
                        throw error
                    }
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
                updateSourceRevenueAnalyticsConfig: async ({
                    source,
                    config,
                }: {
                    source: ExternalDataSource
                    config: Partial<ExternalDataSourceRevenueAnalyticsConfig>
                }) => {
                    const updatedSource = await api.externalDataSources.updateRevenueAnalyticsConfig(source.id, config)
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
])
