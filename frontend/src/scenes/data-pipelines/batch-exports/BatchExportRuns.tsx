import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, LemonTable, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { IconCancel, IconRefresh } from 'lib/lemon-ui/icons'

import { BatchExportConfiguration, BatchExportRun, GroupedBatchExportRuns } from '~/types'

import { pipelineAccessLogic } from '../../pipeline/pipelineAccessLogic'
import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { batchExportRunsLogic, BatchExportRunsLogicProps } from './batchExportRunsLogic'

function isRunInProgress(run: BatchExportRun): boolean {
    return ['Running', 'Starting'].includes(run.status)
}

export function BatchExportRuns({ id }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id })

    const { batchExportConfig, groupedRuns, loading, hasMoreRunsToLoad, usingLatestRuns } = useValues(logic)
    const { loadOlderRuns, retryRun } = useActions(logic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <>
            <div className="deprecated-space-y-2">
                <BatchExportRunsFilters id={id} />
                {usingLatestRuns ? (
                    <BatchExportLatestRuns id={id} />
                ) : (
                    <BatchExportRunsGrouped
                        id={id}
                        groupedRuns={groupedRuns}
                        loading={loading}
                        retryRun={retryRun}
                        hasMoreRunsToLoad={hasMoreRunsToLoad}
                        loadOlderRuns={loadOlderRuns}
                        interval={batchExportConfig.interval}
                    />
                )}
            </div>
            <BatchExportBackfillModal id={id} />
        </>
    )
}

function BatchExportRunsFilters({ id }: { id: string }): JSX.Element {
    const logic = batchExportRunsLogic({ id })
    const { dateRange, usingLatestRuns, loading } = useValues(logic)
    const { setDateRange, switchLatestRuns, loadRuns } = useActions(logic)

    return (
        <div className="flex gap-2 items-center">
            <LemonButton onClick={loadRuns} loading={loading} type="secondary" icon={<IconRefresh />} size="small">
                Refresh
            </LemonButton>
            <LemonSwitch
                bordered
                label="Show latest runs"
                checked={usingLatestRuns}
                onChange={switchLatestRuns}
                size="small"
            />
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
        </div>
    )
}

function BatchExportLatestRuns({ id }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id })

    const { batchExportConfig, latestRuns, loading, hasMoreRunsToLoad } = useValues(logic)
    const { openBackfillModal, loadOlderRuns, retryRun, cancelRun } = useActions(logic)
    const { canEnableNewDestinations } = useValues(pipelineAccessLogic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <>
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
                            return run.data_interval_start ? (
                                <TZLabel
                                    time={run.data_interval_start}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="HH:mm:ss"
                                />
                            ) : (
                                'Beginning of time'
                            )
                        },
                    },
                    {
                        title: 'Data interval end',
                        key: 'dataIntervalEnd',
                        tooltip: 'End of the time range to export',
                        render: (_, run) => {
                            return (
                                <TZLabel
                                    time={run.data_interval_end}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="HH:mm:ss"
                                />
                            )
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
                                return (
                                    <div className="flex gap-1">
                                        <RunRetryButton run={run} retryRun={retryRun} />
                                        <RunCancelButton run={run} cancelRun={cancelRun} />
                                    </div>
                                )
                            }
                        },
                    },
                ]}
                emptyState={
                    <div className="deprecated-space-y-2">
                        <div>
                            No runs in this time range. Your exporter runs every <b>{batchExportConfig.interval}</b>.
                        </div>
                        {canEnableNewDestinations && (
                            <LemonButton type="primary" onClick={() => openBackfillModal()}>
                                Start backfill
                            </LemonButton>
                        )}
                    </div>
                }
            />
        </>
    )
}

export function BatchExportRunsGrouped({
    id,
    groupedRuns,
    loading,
    retryRun,
    hasMoreRunsToLoad,
    loadOlderRuns,
    interval,
}: {
    id: string
    groupedRuns: GroupedBatchExportRuns[]
    loading: boolean
    retryRun: any
    hasMoreRunsToLoad: boolean
    loadOlderRuns: any
    interval: BatchExportConfiguration['interval']
}): JSX.Element {
    const logic = batchExportRunsLogic({ id })

    const { canEnableNewDestinations } = useValues(pipelineAccessLogic)
    const { openBackfillModal } = useActions(logic)

    return (
        <>
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
                            return run.data_interval_start ? (
                                <TZLabel
                                    time={run.data_interval_start}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="HH:mm:ss"
                                />
                            ) : (
                                'Beginning of time'
                            )
                        },
                    },
                    {
                        title: 'Data interval end',
                        key: 'dataIntervalEnd',
                        tooltip: 'End of the time range to export',
                        render: (_, run) => {
                            return (
                                <TZLabel
                                    time={run.data_interval_end}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="HH:mm:ss"
                                />
                            )
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
                                return <RunRetryButton run={groupedRun.runs[0]} retryRun={retryRun} />
                            }
                        },
                    },
                ]}
                emptyState={
                    <div className="deprecated-space-y-2">
                        <div>
                            No runs in this time range. Your exporter runs every <b>{interval}</b>.
                        </div>
                        {canEnableNewDestinations && (
                            <LemonButton type="primary" onClick={() => openBackfillModal()}>
                                Start backfill
                            </LemonButton>
                        )}
                    </div>
                }
            />
        </>
    )
}

function RunRetryButton({ run, retryRun }: { run: any; retryRun: any }): JSX.Element {
    return (
        <span className="flex gap-1 items-center">
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

function RunCancelButton({ run, cancelRun }: { run: BatchExportRun; cancelRun: any }): JSX.Element {
    return (
        <span className="flex gap-1 items-center">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconCancel />}
                disabledReason={
                    run.status === 'Running' || run.status === 'Starting'
                        ? null
                        : `Cannot cancel as run is '${run.status}'`
                }
                onClick={() =>
                    LemonDialog.open({
                        title: 'Cancel run?',
                        description: (
                            <>
                                <p>This will cancel the selected backfill run.</p>
                            </>
                        ),
                        width: '20rem',
                        primaryButton: {
                            children: 'Cancel run',
                            onClick: () => cancelRun(run),
                        },
                        secondaryButton: {
                            children: 'Go back',
                        },
                    })
                }
            />
        </span>
    )
}

export function BatchExportRunIcon({
    runs,
    showLabel = false,
}: {
    runs: BatchExportRun[]
    showLabel?: boolean
}): JSX.Element {
    // We assume these are pre-sorted
    const latestRun = runs[0]

    const status = combineFailedStatuses(latestRun.status)
    const color = colorForStatus(status)

    return (
        <Tooltip
            title={
                <>
                    Run status: {status}
                    {runs.length > 1 && (
                        <>
                            <br />
                            Attempts: {runs.length}
                        </>
                    )}
                </>
            }
        >
            <span
                className={clsx(
                    `BatchExportRunIcon h-6 p-2 border-2 flex items-center justify-center rounded-full font-semibold text-xs border-${color} text-${color}-dark select-none`,
                    color === 'primary' && 'BatchExportRunIcon--pulse',
                    showLabel ? '' : 'w-6'
                )}
            >
                {showLabel ? <span className="text-center">{status}</span> : runs.length}
            </span>
        </Tooltip>
    )
}

const combineFailedStatuses = (status: BatchExportRun['status']): BatchExportRun['status'] => {
    // Eventually we should expose the difference between "Failed" and "FailedRetryable" to the user,
    // because "Failed" tends to mean their configuration or destination is broken.
    if (status === 'FailedRetryable') {
        return 'Failed'
    }
    return status
}

const colorForStatus = (status: BatchExportRun['status']): 'success' | 'primary' | 'warning' | 'danger' | 'default' => {
    switch (status) {
        case 'Completed':
            return 'success'
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            return 'primary'
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            return 'warning'
        case 'Failed':
        case 'FailedRetryable':
            return 'danger'
        default:
            return 'default'
    }
}
