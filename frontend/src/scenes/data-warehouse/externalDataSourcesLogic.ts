import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({
        abortAnyRunningQuery: true,
        deleteSource: (source: ExternalDataSource) => ({ source }),
        reloadSource: (source: ExternalDataSource) => ({ source }),
        reloadSourceSuccess: (source: ExternalDataSource) => ({ source }),
        reloadSourceFailure: (source: ExternalDataSource, error: any) => ({ source, error }),
    }),
    loaders(({ cache, actions, values }) => ({
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
                            values.dataWarehouseSources?.results.map((s) =>
                                s.id === updatedSource.id ? updatedSource : s
                            ) || [],
                    } as PaginatedResponse<ExternalDataSource>
                },
            },
        ],
    })),
    reducers(() => ({
        dataWarehouseSourcesLoading: [
            false as boolean,
            {
                loadSources: () => true,
                loadSourcesFailure: () => false,
                loadSourcesSuccess: () => false,
            },
        ],
    })),
    listeners(({ cache, actions }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        deleteSource: async ({ source }) => {
            await api.externalDataSources.delete(source.id)
            actions.loadSources(null)
        },
        reloadSource: async ({ source }) => {
            try {
                await api.externalDataSources.reload(source.id)
                actions.loadSources(null)
                actions.reloadSourceSuccess(source)
            } catch (e: any) {
                actions.reloadSourceFailure(source, e)
            }
        },
    })),
])
