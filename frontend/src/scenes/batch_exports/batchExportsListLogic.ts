import { actions, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import { BatchExportConfiguration } from '~/types'

import api, { CountedPaginatedResponse } from 'lib/api'

import type { batchExportsListLogicType } from './batchExportsListLogicType'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'

const PAGE_SIZE = 10
// Refresh the current page of exports periodically to see whats up.
const REFRESH_INTERVAL = 10000

export const batchExportsListLogic = kea<batchExportsListLogicType>([
    path(['scenes', 'batch_exports', 'batchExportsListLogic']),
    actions({
        loadBatchExports: (offset?: number) => ({ offset }),
    }),

    reducers({
        offset: [
            0,
            {
                loadBatchExports: (_, { offset }) => offset || 0,
            },
        ],
    }),

    loaders(({}) => ({
        batchExportConfigs: [
            null as null | CountedPaginatedResponse<BatchExportConfiguration>,
            {
                loadBatchExports: async ({ offset }, breakpoint) => {
                    // TODO: Support pagination
                    await breakpoint(100)
                    const res = await api.batchExports.list({
                        offset: offset || 0,
                        limit: PAGE_SIZE,
                    })
                    return res
                },
            },
        ],
    })),

    listeners(({ actions, values, cache }) => ({
        loadBatchExportsSuccess: () => {
            clearTimeout(cache.refreshTimeout)

            cache.refreshTimeout = setTimeout(() => {
                actions.loadBatchExports(values.offset)
            }, REFRESH_INTERVAL)
        },
    })),

    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
    }),

    selectors(({ actions }) => ({
        pagination: [
            (s) => [s.offset, s.batchExportConfigs],
            (offset, configs): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: PAGE_SIZE,
                    currentPage: Math.floor(offset / PAGE_SIZE) + 1,
                    entryCount: configs?.count ?? 0,
                    onBackward: () => actions.loadBatchExports(offset - PAGE_SIZE),
                    onForward: () => actions.loadBatchExports(offset + PAGE_SIZE),
                }
            },
        ],
    })),
])
