import { lemonToast } from '@posthog/lemon-ui'
import { actions, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BatchExportConfiguration, BatchExportRun, Breadcrumb, GroupedBatchExportRuns } from '~/types'

import type { batchExportLogicType } from './batchExportLogicType'

export type BatchExportLogicProps = {
    id: string
}

export enum BatchExportTab {
    Runs = 'runs',
    Logs = 'logs',
}

// TODO: Fix this
const RUNS_REFRESH_INTERVAL = 5000

const convert = (run: BatchExportRun): BatchExportRun => {
    return {
        ...run,
        data_interval_start: dayjs(run.data_interval_start),
        data_interval_end: dayjs(run.data_interval_end),
        created_at: dayjs(run.created_at),
        last_updated_at: run.last_updated_at ? dayjs(run.last_updated_at) : undefined,
    }
}

const mergeRuns = (oldRuns: BatchExportRun[], newRuns: BatchExportRun[]): BatchExportRun[] => {
    const runs = [...oldRuns]

    newRuns.forEach((rawRun) => {
        const newRun = convert(rawRun)
        const index = runs.findIndex((run) => run.id === newRun.id)

        if (index > -1) {
            runs[index] = newRun
        } else {
            runs.push(newRun)
        }
    })

    return runs
}

export const batchExportLogic = kea<batchExportLogicType>([
    props({} as BatchExportLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportLogic', key]),

    actions({
        loadBatchExportRuns: true,
        loadNextBatchExportRuns: true,
        openBackfillModal: true,
        closeBackfillModal: true,
        retryRun: (run: BatchExportRun) => ({ run }),
        setRunsDateRange: (data: { from: Dayjs; to: Dayjs }) => data,
        setActiveTab: (tab: BatchExportTab) => ({ tab }),
    }),

    reducers({
        activeTab: [
            'runs' as BatchExportTab | null,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        runsDateRange: [
            { from: dayjs().subtract(7, 'day').startOf('day'), to: dayjs().endOf('day') } as { from: Dayjs; to: Dayjs },
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
    }),

    loaders(({ props, values }) => ({
        batchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    const res = await api.batchExports.get(props.id)
                    return res
                },

                pause: async () => {
                    if (!values.batchExportConfig) {
                        return null
                    }
                    await api.batchExports.pause(props.id)
                    lemonToast.success('Batch export paused. No future runs will be scheduled')
                    return {
                        ...values.batchExportConfig,
                        paused: true,
                    }
                },
                unpause: async () => {
                    if (!values.batchExportConfig) {
                        return null
                    }
                    await api.batchExports.unpause(props.id)
                    lemonToast.success('Batch export unpaused. Future runs will be scheduled')
                    return {
                        ...values.batchExportConfig,
                        paused: false,
                    }
                },
                archive: async () => {
                    if (!values.batchExportConfig) {
                        return null
                    }
                    await api.batchExports.delete(props.id)

                    router.actions.replace(urls.batchExports())
                    return null
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

                    res.results = mergeRuns(values.batchExportRunsResponse?.results ?? [], res.results)

                    return res
                },
                loadNextBatchExportRuns: async () => {
                    const nextUrl = values.batchExportRunsResponse?.next

                    if (!nextUrl) {
                        return values.batchExportRunsResponse
                    }

                    const res = await api.get<PaginatedResponse<BatchExportRun>>(nextUrl)

                    res.results = mergeRuns(values.batchExportRunsResponse?.results ?? [], res.results)

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

    selectors(() => ({
        groupedRuns: [
            (s) => [s.batchExportRuns],
            (runs): GroupedBatchExportRuns[] => {
                // Runs are grouped by the date range they cover
                const groupedRuns: Record<string, GroupedBatchExportRuns> = {}

                runs.forEach((run) => {
                    const key = `${run.data_interval_start}-${run.data_interval_end}`
                    if (!groupedRuns[key]) {
                        groupedRuns[key] = {
                            data_interval_start: run.data_interval_start,
                            data_interval_end: run.data_interval_end,
                            runs: [],
                            last_run_at: run.created_at,
                        }
                    }

                    groupedRuns[key].runs.push(run)
                    groupedRuns[key].runs.sort((a, b) => b.created_at.diff(a.created_at))
                    groupedRuns[key].last_run_at = groupedRuns[key].runs[0].created_at
                })

                return Object.values(groupedRuns).sort((a, b) => b.data_interval_end.diff(a.data_interval_end))
            },
        ],
        breadcrumbs: [
            (s) => [s.batchExportConfig],
            (config): Breadcrumb[] => [
                {
                    key: Scene.BatchExports,
                    name: 'Batch Exports',
                    path: urls.batchExports(),
                },
                {
                    key: [Scene.BatchExport, config?.id || 'loading'],
                    name: config?.name,
                },
            ],
        ],

        batchExportRuns: [
            (s) => [s.batchExportRunsResponse],
            (batchExportRunsResponse): BatchExportRun[] => batchExportRunsResponse?.results ?? [],
        ],

        defaultTab: [(s) => [s.batchExportConfig], () => BatchExportTab.Runs],
    })),

    listeners(({ actions, cache, props }) => ({
        setRunsDateRange: () => {
            actions.loadBatchExportRuns()
        },
        loadBatchExportRunsSuccess: () => {
            clearTimeout(cache.refreshTimeout)

            // NOTE: This isn't perfect - it assumes that the first page will contain the currently running run.
            // In practice the in progress runs are almost always in the first page
            cache.refreshTimeout = setTimeout(() => {
                actions.loadBatchExportRuns()
            }, RUNS_REFRESH_INTERVAL)
        },

        retryRun: async ({ run }) => {
            await api.batchExports.createBackfill(props.id, {
                start_at: run.data_interval_start.toISOString(),
                end_at: run.data_interval_end.toISOString(),
            })

            lemonToast.success('Retry has been scheduled.')

            clearTimeout(cache.refreshTimeout)
            cache.refreshTimeout = setTimeout(() => {
                actions.loadBatchExportRuns()
            }, 2000)
        },
    })),

    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
    }),
])
