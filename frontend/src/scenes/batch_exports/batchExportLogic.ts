import { actions, kea, key, path, props, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import { BatchExportConfiguration, BatchExportRun, Breadcrumb } from '~/types'

import api, { CountedPaginatedResponse } from 'lib/api'

import type { batchExportLogicType } from './batchExportLogicType'
import { urls } from 'scenes/urls'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'

export type BatchExportLogicProps = {
    id: string
}

const RUNS_PAGE_SIZE = 30

export const batchExportLogic = kea<batchExportLogicType>([
    props({} as BatchExportLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportLogic', key]),

    actions({
        loadBatchExportRuns: (offset?: number) => ({ offset }),
    }),

    loaders(({ props }) => ({
        batchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    const res = await api.batchExports.get(props.id)
                    return res
                },
            },
        ],

        batchExportRuns: [
            null as CountedPaginatedResponse<BatchExportRun> | null,
            {
                loadBatchExportRuns: async () => {
                    const res = await api.batchExports.listRuns(props.id, {
                        limit: RUNS_PAGE_SIZE,
                    })

                    return res
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        batchExportRunsPagination: [
            (s) => [s.batchExportRuns],
            (batchExportRuns): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: RUNS_PAGE_SIZE,
                    currentPage: 1,
                    entryCount: batchExportRuns?.count,
                    onBackward: () => actions.loadBatchExportConfig(0),
                    onForward: () => actions.loadBatchExportConfig(10),
                }
            },
        ],
        breadcrumbs: [
            (s) => [s.batchExportConfig],
            (config): Breadcrumb[] => [
                {
                    name: 'Batch Exports',
                    path: urls.batchExports(),
                },
                {
                    name: config?.name ?? 'Loading',
                },
            ],
        ],
    })),
])
