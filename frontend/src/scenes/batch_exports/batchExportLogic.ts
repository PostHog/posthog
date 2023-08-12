import { actions, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import { BatchExportConfiguration, BatchExportRun, Breadcrumb } from '~/types'

import api, { PaginatedResponse } from 'lib/api'

import { lemonToast } from '@posthog/lemon-ui'
import { forms } from 'kea-forms'
import { Dayjs, dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'
import type { batchExportLogicType } from './batchExportLogicType'

export type BatchExportLogicProps = {
    id: string
}

// TODO: Fix this
const RUNS_REFRESH_INTERVAL = 5000

export const batchExportLogic = kea<batchExportLogicType>([
    props({} as BatchExportLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportLogic', key]),

    actions({
        loadBatchExportRuns: true,
        loadNextBatchExportRuns: true,
        openBackfillModal: true,
        closeBackfillModal: true,
        retryRun: (runId: BatchExportRun) => ({ runId }),
        setRunsDateRange: (data: { from: Dayjs; to: Dayjs }) => data,
    }),

    reducers({
        runsDateRange: [
            { from: dayjs().subtract(7, 'day').startOf('day'), to: dayjs().endOf('day') },
            {
                setRunsDateRange: (_, { from, to }) => ({ from, to }),
            },
        ],
        isBackfillModalOpen: [
            false,
            {
                openBackfillModal: () => true,
                closeBackfillModal: () => false,
            },
        ],

        batchExportRuns: [
            [] as BatchExportRun[],

            {
                loadBatchExportRunsSuccess: (_, { batchExportRunsResponse }) => {
                    return batchExportRunsResponse.results
                },
                loadNextBatchExportRunsSuccess: (state, { batchExportRunsResponse }) => {
                    return [...state, ...(batchExportRunsResponse?.results ?? [])]
                },
            },
        ],
    }),

    loaders(({ props, values }) => ({
        batchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    const res = await api.batchExports.get(props.id)
                    return res
                },
            },
        ],

        batchExportRunsResponse: [
            null as PaginatedResponse<BatchExportRun> | null,
            {
                loadBatchExportRuns: async () => {
                    const res = await api.batchExports.listRuns(props.id, {
                        after: values.runsDateRange.from,
                        before: values.runsDateRange.to.add(1, 'day'),
                    })

                    return res
                },
                loadNextBatchExportRuns: async () => {
                    const nextUrl = values.batchExportRunsResponse?.next

                    if (!nextUrl) {
                        return values.batchExportRunsResponse
                    }

                    const res = await api.get<PaginatedResponse<BatchExportRun>>(nextUrl)

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
                await api.batchExports
                    .createBackfill(props.id, {
                        start_at: start_at?.toISOString() ?? null,
                        end_at: end_at?.toISOString() ?? null,
                    })
                    .catch((e) => {
                        if (e.detail) {
                            actions.setBackfillFormManualErrors({
                                [e.attr ?? 'start_at']: e.detail,
                            })
                        } else {
                            lemonToast.error('Unknown error occurred')
                        }

                        throw e
                    })

                actions.closeBackfillModal()
                actions.loadBatchExportRuns()

                return
            },
        },
    })),

    selectors(({}) => ({
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

    listeners(({ actions, cache }) => ({
        setRunsDateRange: () => {
            actions.loadBatchExportRuns()
        },
        loadBatchExportRunsSuccess: () => {
            clearTimeout(cache.refreshTimeout)

            // NOTE: Here we should load only newer runs and refresh any in a non-complete state...
            // cache.refreshTimeout = setTimeout(() => {
            //     actions.loadBatchExportRuns()
            // }, RUNS_REFRESH_INTERVAL)
        },
    })),

    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
    }),
])
