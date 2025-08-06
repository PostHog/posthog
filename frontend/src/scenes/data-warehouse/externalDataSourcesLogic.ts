import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({}),
    loaders(({ cache, values }) => ({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadSources: async (_, breakpoint) => {
                    await breakpoint(300)

                    // Clean up any existing abort controller
                    if (cache.abortController) {
                        cache.abortController.abort()
                    }

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
                            values.dataWarehouseSources?.results.map((s) => (s.id === updatedSource.id ? source : s)) ||
                            [],
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
])
