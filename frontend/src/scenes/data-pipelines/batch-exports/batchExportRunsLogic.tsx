import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { BatchExportRun, GroupedBatchExportRuns, RawBatchExportRun } from '~/types'

import { batchExportBackfillModalLogic } from './batchExportBackfillModalLogic'
import { batchExportConfigurationLogic } from './batchExportConfigurationLogic'
import type { batchExportRunsLogicType } from './batchExportRunsLogicType'

const DEFAULT_DATE_FROM = '-2d'
export interface BatchExportRunsLogicProps {
    id: string
}

export const batchExportRunsLogic = kea<batchExportRunsLogicType>([
    props({} as BatchExportRunsLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'batchExportRunsLogic', key]),
    connect((props: BatchExportRunsLogicProps) => ({
        values: [
            batchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['batchExportConfig'],
        ],
        actions: [batchExportBackfillModalLogic(props), ['submitBackfillFormSuccess', 'openBackfillModal']],
    })),
    actions({
        setDateRange: (from: string | null, to: string | null) => ({ from, to }),
        switchLatestRuns: (enabled: boolean) => ({ enabled }),
        loadRuns: true,
        retryRun: (run: BatchExportRun) => ({ run }),
        cancelRun: (run: BatchExportRun) => ({ run }),
    }),
    loaders(({ props, values }) => ({
        runsPaginatedResponse: [
            null as PaginatedResponse<RawBatchExportRun> | null,
            {
                loadRuns: async () => {
                    // TODO: loading and combining the data could be more efficient
                    if (values.usingLatestRuns) {
                        return await api.batchExports.listRuns(props.id, {})
                    }

                    return await api.batchExports.listRuns(props.id, {
                        start: values.dateRange.from,
                        end: values.dateRange.to, // TODO: maybe add 1 day
                        ordering: '-data_interval_start',
                    })
                },
                loadOlderRuns: async () => {
                    const nextUrl = values.runsPaginatedResponse?.next

                    if (!nextUrl) {
                        return values.runsPaginatedResponse
                    }
                    const res = await api.get<PaginatedResponse<RawBatchExportRun>>(nextUrl)
                    res.results = [...(values.runsPaginatedResponse?.results ?? []), ...res.results]

                    return res
                },
            },
        ],
    })),
    reducers({
        dateRange: [
            { from: DEFAULT_DATE_FROM, to: null } as { from: string; to: string | null },
            {
                setDateRange: (_, { from, to }) => ({ from: from ?? DEFAULT_DATE_FROM, to: to }),
            },
        ],
        usingLatestRuns: [
            true,
            {
                switchLatestRuns: (_, { enabled }) => enabled,
            },
        ],
    }),
    selectors({
        hasMoreRunsToLoad: [(s) => [s.runsPaginatedResponse], (runsPaginatedResponse) => !!runsPaginatedResponse?.next],
        loading: [
            (s) => [s.runsPaginatedResponseLoading],
            (runsPaginatedResponseLoading) => runsPaginatedResponseLoading,
        ],
        latestRuns: [
            // These aren't grouped because they might not include all runs for a time interval
            (s) => [s.runsPaginatedResponse],
            (runsPaginatedResponse): BatchExportRun[] => {
                const runs = runsPaginatedResponse?.results ?? []
                return runs.map((run) => {
                    return {
                        ...run,
                        created_at: dayjs(run.created_at),
                        data_interval_start: run.data_interval_start ? dayjs(run.data_interval_start) : undefined,
                        data_interval_end: dayjs(run.data_interval_end),
                        last_updated_at: run.last_updated_at ? dayjs(run.last_updated_at) : undefined,
                    }
                })
            },
        ],
        groupedRuns: [
            (s) => [s.runsPaginatedResponse, s.usingLatestRuns],
            (runsPaginatedResponse, usingLatestRuns): GroupedBatchExportRuns[] => {
                if (usingLatestRuns) {
                    return []
                }
                const runs = runsPaginatedResponse?.results ?? []

                // Runs are grouped by the date range they cover
                const groupedRuns: Record<string, GroupedBatchExportRuns> = {}

                runs.forEach((run) => {
                    if (!run.data_interval_start) {
                        // For now, don't include backfill runs in here as it gets
                        // complicated to sort and group.
                        return
                    }

                    const key = `${run.data_interval_start}-${run.data_interval_end}`

                    if (!groupedRuns[key]) {
                        groupedRuns[key] = {
                            data_interval_start: dayjs(run.data_interval_start),
                            data_interval_end: dayjs(run.data_interval_end),
                            runs: [],
                            last_run_at: dayjs(run.created_at),
                        }
                    }

                    groupedRuns[key].runs.push({
                        ...run,
                        created_at: dayjs(run.created_at),
                        data_interval_start: run.data_interval_start ? dayjs(run.data_interval_start) : undefined,
                        data_interval_end: dayjs(run.data_interval_end),
                        last_updated_at: run.last_updated_at ? dayjs(run.last_updated_at) : undefined,
                    })
                    groupedRuns[key].runs.sort((a, b) => b.created_at.diff(a.created_at))
                    groupedRuns[key].last_run_at = groupedRuns[key].runs[0].created_at
                })

                return Object.values(groupedRuns)
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        setDateRange: () => {
            actions.loadRuns()
        },
        switchLatestRuns: () => {
            actions.loadRuns()
        },
        retryRun: async ({ run }) => {
            await api.batchExports.retryRun(props.id, run.id)
            lemonToast.success('Retry has been scheduled.')
        },
        cancelRun: async ({ run }) => {
            await api.batchExports.cancelRun(props.id, run.id)
            lemonToast.success('Run has been cancelled.')
        },
        submitBackfillFormSuccess: () => {
            actions.loadRuns()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRuns()
    }),
])
