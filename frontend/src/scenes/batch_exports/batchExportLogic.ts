import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import { BatchExportConfiguration, BatchExportRun, Breadcrumb } from '~/types'

import api, { CountedPaginatedResponse } from 'lib/api'

import type { batchExportLogicType } from './batchExportLogicType'
import { urls } from 'scenes/urls'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { forms } from 'kea-forms'
import { Dayjs, dayjs } from 'lib/dayjs'

export type BatchExportLogicProps = {
    id: string
}

const RUNS_PAGE_SIZE = 100

export const batchExportLogic = kea<batchExportLogicType>([
    props({} as BatchExportLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportLogic', key]),

    actions({
        loadBatchExportRuns: (offset?: number) => ({ offset }),
        openBackfillModal: true,
        closeBackfillModal: true,
    }),

    reducers({
        isBackfillModalOpen: [
            false,
            {
                openBackfillModal: () => true,
                closeBackfillModal: () => false,
            },
        ],
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
                loadBatchExportRuns: async ({ offset }) => {
                    const res = await api.batchExports.listRuns(props.id, {
                        limit: RUNS_PAGE_SIZE,
                    })

                    return res
                },
            },
        ],
    })),

    forms(({ props, actions }) => ({
        backfillForm: {
            defaults: { end_at: dayjs() } as {
                start_at?: Dayjs
                end_at?: Dayjs
            },
            errors: ({ start_at, end_at }) => ({
                start_at: !start_at ? 'Start date is required' : undefined,
                end_at: !end_at ? 'End date is required' : undefined,
            }),
            submit: async ({ start_at, end_at }) => {
                await new Promise((resolve) => setTimeout(resolve, 1000))
                await api.batchExports.createBackfill(props.id, {
                    start_at: start_at?.toISOString() ?? null,
                    end_at: end_at?.toISOString() ?? null,
                })

                actions.closeBackfillModal()

                return
            },
        },
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
