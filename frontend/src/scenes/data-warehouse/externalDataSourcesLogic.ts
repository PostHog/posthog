import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    loaders({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadSources: (options?: ApiMethodOptions | null) => {
                    return api.externalDataSources.list(options ?? undefined)
                },
            },
        ],
    }),
])
