import { useActions, useValues } from 'kea'

import { IconCalendar, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { IconCancel } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, humanFriendlyNumber, humanizeBytes } from 'lib/utils'

import { BatchExportConfiguration, BatchExportRun, GroupedBatchExportRuns } from '~/types'

import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { BatchExportLoadingSkeleton } from './BatchExportLoadingSkeleton'
import { BatchExportRunsLogicProps, batchExportRunsLogic } from './batchExportRunsLogic'
import { BatchExportContext } from './types'
import { statusToLemonTagType } from './utils'

function isRunInProgress(run: BatchExportRun): boolean {
    return ['Running', 'Starting'].includes(run.status)
}

export function BatchExportRuns({ id, context }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id, context })

    const { batchExportConfig, batchExportConfigLoading, groupedRuns, loading, hasMoreRunsToLoad, usingLatestRuns } =
        useValues(logic)
    const { loadOlderRuns, retryRun } = useActions(logic)

    if (!batchExportConfig) {
        if (batchExportConfigLoading) {
            return <BatchExportLoadingSkeleton />
        }
        return <NotFound object="batch export" />
    }

    return (
        <>
            <div className="deprecated-space-y-2">
                <BatchExportRunsFilters id={id} />
                {usingLatestRuns ? (
                    <BatchExportLatestRuns id={id} context={context} />
                ) : (
                    <BatchExportRunsGrouped
                        id={id}
                        context={context}
                        groupedRuns={groupedRuns}
                        loading={loading}
                        retryRun={retryRun}
                        hasMoreRunsToLoad={hasMoreRunsToLoad}
                        loadOlderRuns={loadOlderRuns}
                        interval={batchExportConfig.interval}
                    />
                )}
            </div>
            <BatchExportBackfillModal id={id} context={context} />
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

function BatchExportLatestRuns({ id, context }: BatchExportRunsLogicProps): JSX.Element {
    const logic = batchExportRunsLogic({ id, context })

    const { batchExportConfig, latestRuns, loading, hasMoreRunsToLoad, recordLabel } = useValues(logic)
    const { openBackfillModal, loadOlderRuns, retryRun, cancelRun } = useActions(logic)

    if (!batchExportConfig) {
        return <NotFound object="batch export" />
    }

    return (
        <>
            <LemonTable<BatchExportRun>
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
                        title: `${capitalizeFirstLetter(recordLabel)} exported`,
                        key: 'rowsExported',
                        render: (_, run) => <RecordsExportedCell run={run} />,
                    },
                    // Only show bytes exported column for batch exports
                    ...(context !== 'hog_function'
                        ? [
                              {
                                  title: 'Bytes exported',
                                  key: 'bytesExported',
                                  render: (_: any, run: BatchExportRun) => {
                                      if (run.bytes_exported == null) {
                                          return ''
                                      }
                                      return humanizeBytes(run.bytes_exported)
                                  },
                              },
                          ]
                        : []),
                    {
                        title: 'Run start',
                        key: 'runStart',
                        tooltip: 'Date and time when this run started',
                        render: (_, run) => <TZLabel time={run.created_at} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, run) {
                            return (
                                <div className="flex gap-1">
                                    <RunRetryButton run={run} retryRun={retryRun} />
                                    <RunCancelButton run={run} cancelRun={cancelRun} />
                                </div>
                            )
                        },
                    },
                ]}
                emptyState={
                    <div className="deprecated-space-y-2">
                        <div>
                            No runs in this time range. Your exporter runs every <b>{batchExportConfig.interval}</b>.
                        </div>
                        <LemonButton type="primary" onClick={() => openBackfillModal()}>
                            Start backfill
                        </LemonButton>
                    </div>
                }
            />
        </>
    )
}

export function BatchExportRunsGrouped({
    id,
    context,
    groupedRuns,
    loading,
    retryRun,
    hasMoreRunsToLoad,
    loadOlderRuns,
    interval,
}: {
    id: string
    context?: BatchExportContext
    groupedRuns: GroupedBatchExportRuns[]
    loading: boolean
    retryRun: any
    hasMoreRunsToLoad: boolean
    loadOlderRuns: any
    interval: BatchExportConfiguration['interval']
}): JSX.Element {
    const logic = batchExportRunsLogic({ id, context })

    const { openBackfillModal } = useActions(logic)
    const { recordLabel } = useValues(logic)

    return (
        <>
            <LemonTable<GroupedBatchExportRuns>
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
                            <LemonTable<BatchExportRun>
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
                                        title: `${capitalizeFirstLetter(recordLabel)} exported`,
                                        key: 'rowsExported',
                                        render: (_, run) => <RecordsExportedCell run={run} />,
                                    },
                                    // Only show bytes exported column for batch exports
                                    ...(context !== 'hog_function'
                                        ? [
                                              {
                                                  title: 'Bytes exported',
                                                  key: 'bytesExported',
                                                  render: (_: any, run: BatchExportRun) => {
                                                      if (run.bytes_exported == null) {
                                                          return ''
                                                      }
                                                      return humanizeBytes(run.bytes_exported)
                                                  },
                                              },
                                          ]
                                        : []),
                                    {
                                        title: 'Run start',
                                        key: 'runStart',
                                        tooltip: 'Date and time when this run started',
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
                        tooltip: 'Date and time when this run started',
                        render: (_, groupedRun) => {
                            return <TZLabel time={groupedRun.last_run_at} />
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, groupedRun) {
                            if (!isRunInProgress(groupedRun.runs[0])) {
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
                        <LemonButton type="primary" onClick={() => openBackfillModal()}>
                            Start backfill
                        </LemonButton>
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
    const tagType = statusToLemonTagType(status, { recordsFailed: latestRun.records_failed })

    return (
        <Tooltip
            title={
                <>
                    Run status: {status}
                    {latestRun.records_failed != null && latestRun.records_failed > 0 ? ' (with failures)' : ''}
                    {runs.length > 1 && (
                        <>
                            <br />
                            Attempts: {runs.length}
                        </>
                    )}
                </>
            }
        >
            <LemonTag
                type={tagType}
                size="medium"
                className={!showLabel ? 'justify-center min-w-[1.25rem] tabular-nums' : undefined}
            >
                {showLabel ? status : runs.length}
            </LemonTag>
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

function RecordsExportedCell({ run }: { run: BatchExportRun }): JSX.Element | string {
    if (run.records_completed == null) {
        return ''
    }
    if (run.records_failed != null && run.records_failed > 0) {
        return (
            <span>
                {humanFriendlyNumber(run.records_completed)}
                <span className="text-warning ml-1">({humanFriendlyNumber(run.records_failed)} failed)</span>
            </span>
        )
    }
    return humanFriendlyNumber(run.records_completed)
}
