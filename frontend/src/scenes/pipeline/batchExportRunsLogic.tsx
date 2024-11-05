import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { BatchExportRun, GroupedBatchExportRuns, RawBatchExportRun } from '~/types'

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
        cancelRun: (run: BatchExportRun) => ({ run }),
        openBackfillModal: true,
        closeBackfillModal: true,
        setEarliestBackfill: true,
        unsetEarliestBackfill: true,
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
        isBackfillModalOpen: [
            false,
            {
                openBackfillModal: () => true,
                closeBackfillModal: () => false,
            },
        ],
        isEarliestBackfill: [
            false,
            {
                setEarliestBackfill: () => true,
                unsetEarliestBackfill: () => false,
            },
        ],
    }),
    forms(({ props, actions, values }) => ({
        backfillForm: {
            defaults: {
                start_at: undefined,
                end_at: dayjs().tz(teamLogic.values.timezone).hour(0).minute(0).second(0).millisecond(0),
                earliest_backfill: false,
            } as {
                start_at?: Dayjs
                end_at?: Dayjs
                earliest_backfill: boolean
            },

            errors: ({ start_at, end_at, earliest_backfill }) => ({
                start_at: !start_at ? (!earliest_backfill ? 'Start date is required' : undefined) : undefined,
                end_at: !end_at ? 'End date is required' : undefined,
                earliest_backfill: undefined,
            }),

            submit: async ({ start_at, end_at, earliest_backfill }) => {
                if (values.batchExportConfig && values.batchExportConfig.interval.endsWith('minutes')) {
                    // TODO: Make this generic for all minute frequencies.
                    // Currently, only 5 minute batch exports are supported.
                    if (
                        (start_at?.minute() !== undefined && !(start_at?.minute() % 5 === 0)) ||
                        (end_at?.minute() !== undefined && !(end_at?.minute() % 5 === 0))
                    ) {
                        lemonToast.error(
                            'Backfilling a 5 minute batch export requires bounds be multiple of five minutes'
                        )
                        return
                    }
                }

                let upperBound = dayjs().tz(teamLogic.values.timezone)
                let period = '1 hour'

                if (values.batchExportConfig && end_at) {
                    if (values.batchExportConfig.interval == 'hour') {
                        upperBound = upperBound.add(1, 'hour')
                    } else if (values.batchExportConfig.interval == 'day') {
                        upperBound = upperBound.hour(0).minute(0).second(0)
                        upperBound = upperBound.add(1, 'day')
                        period = '1 day'
                    } else if (values.batchExportConfig.interval.endsWith('minutes')) {
                        // TODO: Make this generic for all minute frequencies.
                        // Currently, only 5 minute batch exports are supported.
                        upperBound = upperBound.add(5, 'minute')
                        period = '5 minutes'
                    } else {
                        upperBound = upperBound.add(1, 'hour')
                    }

                    if (end_at > upperBound) {
                        lemonToast.error(
                            `Requested backfill end date lies too far into the future. Use an end date that is no more than ${period} from now (in your project's timezone)`
                        )
                        return
                    }
                }

                await new Promise((resolve) => setTimeout(resolve, 1000))
                await api.batchExports
                    .createBackfill(props.id, {
                        start_at: earliest_backfill ? null : start_at?.toISOString() ?? null,
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
                actions.loadRuns()

                return
            },
        },
    })),
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
    })),
    afterMount(({ actions }) => {
        actions.loadRuns()
    }),
])
