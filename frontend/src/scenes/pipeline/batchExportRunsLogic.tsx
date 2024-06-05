import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { BatchExportRun, GroupedBatchExportRuns } from '~/types'

import type { batchExportRunsLogicType } from './batchExportRunsLogicType'
import { pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'

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
            teamLogic(),
            ['currentTeamId'],
            pipelineBatchExportConfigurationLogic({
                id: props.id,
                service: null,
            }),
            ['batchExportConfig'],
        ],
    })),
    actions({
        setDateRange: (from: string | null, to: string | null) => ({ from, to }),
        switchLatestRuns: (enabled: boolean) => ({ enabled }),
        loadRuns: true,
        retryRun: (run: BatchExportRun) => ({ run }),
    }),
    loaders(({ props, values }) => ({
        runsPaginatedResponse: [
            null as PaginatedResponse<BatchExportRun> | null,
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
                    const res = await api.get<PaginatedResponse<BatchExportRun>>(nextUrl)
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
            (runsPaginatedResponse): BatchExportRun[] => runsPaginatedResponse?.results ?? [],
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
            await api.batchExports.createBackfill(props.id, {
                start_at: run.data_interval_start.toISOString(),
                end_at: run.data_interval_end.toISOString(),
            })
            lemonToast.success('Retry has been scheduled.')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRuns()
    }),
])
