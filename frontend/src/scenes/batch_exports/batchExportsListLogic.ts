import { actions, kea, path } from 'kea'

import { loaders } from 'kea-loaders'
import { BatchExportConfiguration } from '~/types'

import api from 'lib/api'

import type { batchExportsListLogicType } from './batchExportsListLogicType'

export const batchExportsListLogic = kea<batchExportsListLogicType>([
    path(['scenes', 'batch_exports', 'batchExportsListLogic']),
    actions({
        loadBatchExports: (offset?: number) => ({ offset }),
    }),

    loaders(({}) => ({
        batchExportConfigs: [
            [] as BatchExportConfiguration[],
            {
                loadBatchExports: async (_, breakpoint) => {
                    // TODO: Support pagination
                    await breakpoint(100)
                    const res = await api.batchExports.list()
                    return res.results
                },
            },
        ],
    })),
])
