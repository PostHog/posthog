import { TZLabel } from '@posthog/apps-common'
import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { BatchExportRunIcon } from 'scenes/batch_exports/components'
import { isRunInProgress } from 'scenes/batch_exports/utils'

import { BatchExportConfiguration, GroupedBatchExportRuns } from '~/types'

import { batchExportRunsLogic, BatchExportRunsLogicProps } from './batchExportRunsLogic'
import { pipelineAccessLogic } from './pipelineAccessLogic'

export function BatchExportRuns({ id }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id })

    const { batchExportConfig, groupedRuns, loading, hasMoreRunsToLoad, usingLatestRuns } = useValues(logic)
    const { loadOlderRuns, retryRun } = useActions(logic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    const dateSelector = <RunsDateSelection id={id} />

    if (usingLatestRuns) {
        return (
            <>
                {dateSelector}
                <BatchExportLatestRuns id={id} />
            </>
        )
    }

    return (
        <>
            {dateSelector}
            <BatchExportRunsGrouped
                groupedRuns={groupedRuns}
                loading={loading}
                retryRun={retryRun}
                hasMoreRunsToLoad={hasMoreRunsToLoad}
                loadOlderRuns={loadOlderRuns}
                interval={batchExportConfig.interval}
                openBackfillModal={() => {}} // TODO
            />
        </>
    )
}

export function RunsDateSelection({ id }: { id: string }): JSX.Element {
    const logic = batchExportRunsLogic({ id })
    const { dateRange, usingLatestRuns, loading } = useValues(logic)
    const { setDateRange, switchLatestRuns, loadRuns } = useActions(logic)

    // TODO: Autoload option similar to frontend/src/queries/nodes/DataNode/AutoLoad.tsx
    const latestToggle = (
        <LemonSwitch bordered label="Show latest runs" checked={usingLatestRuns} onChange={switchLatestRuns} />
    )

    const dateFilter = (
        <DateFilter
            dateTo={dateRange.to}
            dateFrom={dateRange.from}
            disabledReason={usingLatestRuns ? 'Turn off "Show latest runs" to filter by data interval' : undefined}
            onChange={(from, to) => setDateRange(from, to)}
            allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                </>
            )}
        />
    )
    return (
        <div className="flex gap-2">
            <LemonButton onClick={loadRuns} loading={loading} type="secondary" icon={<IconRefresh />}>
                Refresh
            </LemonButton>
            {latestToggle}
            {dateFilter}
        </div>
    )
}

export function BatchExportLatestRuns({ id }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id })

    const { batchExportConfig, latestRuns, loading, hasMoreRunsToLoad } = useValues(logic)
    const { loadOlderRuns, retryRun } = useActions(logic)
    const { canEnableNewDestinations } = useValues(pipelineAccessLogic)

    const openBackfillModal = (): any => {} // TODO

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <LemonTable
            dataSource={latestRuns}
            loading={loading}
            loadingSkeletonRows={5}
            footer={
                hasMoreRunsToLoad && (
                    <div className="flex items-center m-2">
                        <LemonButton center fullWidth onClick={loadOlderRuns} loading={loading}>
                            Load more rows
                        </LemonButton>
                    </div>
                )
            }
            columns={[
                {
                    title: 'Status',
                    key: 'status',
                    width: 0,
                    render: (_, run) => <BatchExportRunIcon runs={[run]} showLabel />,
                },
                {
                    title: 'ID',
                    key: 'runId',
                    render: (_, run) => run.id,
                },
                {
                    title: 'Data interval start',
                    key: 'dataIntervalStart',
                    tooltip: 'Start of the time range to export',
                    render: (_, run) => {
                        return (
                            <TZLabel time={run.data_interval_start} formatDate="MMMM DD, YYYY" formatTime="HH:mm:ss" />
                        )
                    },
                },
                {
                    title: 'Data interval end',
                    key: 'dataIntervalEnd',
                    tooltip: 'End of the time range to export',
                    render: (_, run) => {
                        return <TZLabel time={run.data_interval_end} formatDate="MMMM DD, YYYY" formatTime="HH:mm:ss" />
                    },
                },
                {
                    title: 'Run start',
                    key: 'runStart',
                    tooltip: 'Date and time when this BatchExport run started',
                    render: (_, run) => <TZLabel time={run.created_at} />,
                },
                {
                    key: 'actions',
                    width: 0,
                    render: function RenderActions(_, run) {
                        if (canEnableNewDestinations) {
                            return <RunRetryModal run={run} retryRun={retryRun} />
                        }
                    },
                },
            ]}
            emptyState={
                <>
                    No runs in this time range. Your exporter runs every <b>{batchExportConfig.interval}</b>.
                    <br />
                    {canEnableNewDestinations && (
                        <LemonButton type="primary" onClick={openBackfillModal}>
                            Create historic export
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}

export function BatchExportRunsGrouped({
    groupedRuns,
    loading,
    retryRun,
    hasMoreRunsToLoad,
    loadOlderRuns,
    interval,
    openBackfillModal,
}: {
    groupedRuns: GroupedBatchExportRuns[]
    loading: boolean
    retryRun: any
    hasMoreRunsToLoad: boolean
    loadOlderRuns: any
    interval: BatchExportConfiguration['interval']
    openBackfillModal: any
}): JSX.Element {
    const { canEnableNewDestinations } = useValues(pipelineAccessLogic)

    return (
        <LemonTable
            dataSource={groupedRuns}
            loading={loading}
            loadingSkeletonRows={5}
            footer={
                hasMoreRunsToLoad && (
                    <div className="flex items-center m-2">
                        <LemonButton center fullWidth onClick={loadOlderRuns} loading={loading}>
                            Load more rows
                        </LemonButton>
                    </div>
                )
            }
            expandable={{
                noIndent: true,
                expandedRowRender: (groupedRuns) => {
                    return (
                        <LemonTable
                            dataSource={groupedRuns.runs}
                            embedded={true}
                            columns={[
                                {
                                    title: 'Status',
                                    key: 'status',
                                    width: 0,
                                    render: (_, run) => <BatchExportRunIcon runs={[run]} showLabel />,
                                },
                                {
                                    title: 'ID',
                                    key: 'runId',
                                    render: (_, run) => run.id,
                                },
                                {
                                    title: 'Run start',
                                    key: 'runStart',
                                    tooltip: 'Date and time when this BatchExport run started',
                                    render: (_, run) => <TZLabel time={run.created_at} />,
                                },
                            ]}
                        />
                    )
                },
            }}
            columns={[
                {
                    key: 'icon',
                    width: 0,
                    render: (_, groupedRun) => {
                        return <BatchExportRunIcon runs={groupedRun.runs} />
                    },
                },

                {
                    title: 'Data interval start',
                    key: 'dataIntervalStart',
                    tooltip: 'Start of the time range to export',
                    render: (_, run) => {
                        return (
                            <TZLabel time={run.data_interval_start} formatDate="MMMM DD, YYYY" formatTime="HH:mm:ss" />
                        )
                    },
                },
                {
                    title: 'Data interval end',
                    key: 'dataIntervalEnd',
                    tooltip: 'End of the time range to export',
                    render: (_, run) => {
                        return <TZLabel time={run.data_interval_end} formatDate="MMMM DD, YYYY" formatTime="HH:mm:ss" />
                    },
                },
                {
                    title: 'Latest run start',
                    key: 'runStart',
                    tooltip: 'Date and time when this BatchExport run started',
                    render: (_, groupedRun) => {
                        return <TZLabel time={groupedRun.last_run_at} />
                    },
                },
                {
                    key: 'actions',
                    width: 0,
                    render: function RenderActions(_, groupedRun) {
                        if (!isRunInProgress(groupedRun.runs[0]) && canEnableNewDestinations) {
                            return <RunRetryModal run={groupedRun.runs[0]} retryRun={retryRun} />
                        }
                    },
                },
            ]}
            emptyState={
                <>
                    No runs in this time range. Your exporter runs every <b>{interval}</b>.
                    <br />
                    {canEnableNewDestinations && (
                        <LemonButton type="primary" onClick={openBackfillModal}>
                            Create historic export
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}

export function RunRetryModal({ run, retryRun }: { run: any; retryRun: any }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconRefresh />}
                onClick={() =>
                    LemonDialog.open({
                        title: 'Retry export?',
                        description: (
                            <>
                                <p>
                                    This will schedule a new run for the same interval. Any changes to the configuration
                                    will be applied to the new run.
                                </p>
                                <p>
                                    <b>Please note -</b> there may be a slight delay before the new run appears.
                                </p>
                            </>
                        ),
                        width: '20rem',
                        primaryButton: {
                            children: 'Retry',
                            onClick: () => retryRun(run),
                        },
                        secondaryButton: {
                            children: 'Cancel',
                        },
                    })
                }
            />
        </span>
    )
}
