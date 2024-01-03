import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'

import { BatchExportConfiguration } from '~/types'

import type { batchExportsListLogicType } from './batchExportsListLogicType'

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

    loaders(({ values }) => ({
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

                pause: async (batchExport: BatchExportConfiguration) => {
                    await api.batchExports.pause(batchExport.id)
                    lemonToast.success('Batch export paused. No future runs will be scheduled')

                    const found = values.batchExportConfigs?.results.find((config) => config.id === batchExport.id)

                    if (found) {
                        found.paused = true
                    }

                    return values.batchExportConfigs
                },

                unpause: async (batchExport: BatchExportConfiguration) => {
                    await api.batchExports.unpause(batchExport.id)
                    lemonToast.success('Batch export unpaused. Future runs will be scheduled')

                    const found = values.batchExportConfigs?.results.find((config) => config.id === batchExport.id)

                    if (found) {
                        found.paused = false
                    }

                    return values.batchExportConfigs
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

    afterMount(({ actions }) => {
        actions.loadBatchExports()
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
