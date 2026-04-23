import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError, ApiMethodOptions, PaginatedResponse } from 'lib/api'

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
                        // Transient failures shouldn't surface as exceptions:
                        //   - 403: the user has no access to the endpoint
                        //   - AbortError: abortAnyRunningQuery cancelled this request mid-flight
                        //   - ApiError with no HTTP status: handleFetch wraps native fetch
                        //     failures (offline, DNS, CORS) as ApiError(err, undefined)
                        // Anything else (including kea's BreakPointException) propagates.
                        const isTransient =
                            error?.status === 403 ||
                            error?.name === 'AbortError' ||
                            (error instanceof ApiError && error.status === undefined)
                        if (!isTransient) {
                            throw error
                        }
                        // Bail out if a newer loadSources has superseded this one so we don't
                        // clobber its state with an empty result.
                        breakpoint()
                        cache.abortController = null
                        return { results: [], count: 0, next: null, previous: null }
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
