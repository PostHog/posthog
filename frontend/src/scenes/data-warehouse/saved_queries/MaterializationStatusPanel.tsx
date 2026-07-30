import { useActions, useValues } from 'kea'

import { IconEllipsis, IconWarning } from '@posthog/icons'
import { LemonDialog, LemonTable, Link, Spinner } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, DataModelingJob, LogEntryLevel } from '~/types'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { materializationJobsLogic } from './materializationJobsLogic'
import {
    SYNC_FREQUENCY_OPTIONS,
    jobDurationSeconds,
    jobProgressPercent,
    syncFrequencyPhrase,
} from './materializationStatus'

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

interface MaterializationStatusPanelProps {
    viewId: string
    /**
     * The product surface this panel is rendered in. Endpoints own the materialization lifecycle of their
     * backing saved query, so destructive saved-query controls (revert, sync frequency) must be hidden
     * when `kind === 'endpoint'` — those mutations bypass the endpoint's `_disable_materialization` flow.
     */
    kind?: 'view' | 'endpoint'
}

export function MaterializationStatusPanel({ viewId, kind = 'view' }: MaterializationStatusPanelProps): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId })
    const { savedQuery, savedQueryLoading, panelState, dataModelingJobs, dataModelingJobsLoading } =
        useValues(jobsLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { materializeDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const materializationAccessReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor
    )

    if (!savedQuery) {
        return (
            <div className="flex min-h-64 items-center justify-center" data-attr="materialization-status-panel">
                {savedQueryLoading ? <Spinner className="text-2xl" /> : null}
            </div>
        )
    }

    if (!savedQuery.is_materialized || !panelState) {
        return (
            <div className="flex flex-col gap-2" data-attr="materialization-status-panel">
                <p className="text-sm mb-0">
                    Materialized views pre-compute results on a schedule, so queries read from a stored table instead of
                    running the full query each time.{' '}
                    <Link
                        data-attr="materializing-help"
                        to="https://posthog.com/docs/data-warehouse/views#materializing-and-scheduling-a-view"
                        target="_blank"
                    >
                        Learn more about materialization
                    </Link>
                </p>
                <div>
                    <LemonButton
                        size="small"
                        onClick={() => materializeDataWarehouseSavedQuery(viewId)}
                        type="primary"
                        loading={updatingDataWarehouseSavedQuery}
                        disabledReason={materializationAccessReason}
                    >
                        Materialize
                    </LemonButton>
                </div>
            </div>
        )
    }

    const hasRuns = !!dataModelingJobs?.results?.length

    return (
        <div className="flex flex-col gap-4" data-attr="materialization-status-panel">
            <MaterializationStatusCard viewId={viewId} kind={kind} />
            {(hasRuns || dataModelingJobsLoading) && (
                <div className="flex flex-col gap-2">
                    <h3 className="mb-0">Run history</h3>
                    <MaterializationRunsTable viewId={viewId} />
                </div>
            )}
        </div>
    )
}

export function MaterializationStatusCard({
    viewId,
    kind = 'view',
}: {
    viewId: string
    kind?: 'view' | 'endpoint'
}): JSX.Element | null {
    const accessReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor
    )
    const jobsLogic = materializationJobsLogic({ viewId })
    const {
        panelState,
        savedQuery,
        suspension,
        suspensionEnabled,
        failureStreak,
        currentJob,
        latestCompletedJob,
        lastRunAt,
        nextRunAt,
        startingMaterialization,
        resumingMaterialization,
    } = useValues(jobsLogic)
    const { setStartingMaterialization, resumeMaterialization } = useActions(jobsLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const {
        updateDataWarehouseSavedQuery,
        runDataWarehouseSavedQuery,
        cancelDataWarehouseSavedQuery,
        revertMaterialization,
    } = useActions(dataWarehouseViewsLogic)

    if (!savedQuery || !panelState) {
        return null
    }

    const threshold = failureStreak?.threshold ?? 5
    const streakCount = failureStreak?.count ?? 0
    const failuresLeft = Math.max(1, threshold - streakCount)
    const canEditSyncFrequency =
        kind !== 'endpoint' && !savedQuery.sync_frequency_managed_by_dag && !savedQuery.managed_viewset_kind

    const cardStyle: string =
        panelState === 'suspended'
            ? 'border-danger bg-danger-highlight'
            : panelState === 'failing'
              ? 'border-warning bg-warning-highlight'
              : 'border-primary'

    const statusIcon =
        panelState === 'running' ? (
            <Spinner className="text-base" />
        ) : panelState === 'suspended' ? (
            <IconWarning className="text-danger text-base" />
        ) : panelState === 'failing' ? (
            <IconWarning className="text-warning text-base" />
        ) : (
            <span
                className={`inline-block size-2 rounded-full ${panelState === 'healthy' ? 'bg-success' : 'bg-border-bold'}`}
            />
        )

    const failingTitle = `${streakCount > 1 ? `Last ${streakCount} runs failed` : 'Last run failed'}${
        suspensionEnabled ? ` · pauses after ${failuresLeft} more` : ''
    }`
    const title =
        panelState === 'suspended'
            ? 'Scheduled refreshes are paused'
            : panelState === 'failing'
              ? failingTitle
              : panelState === 'running'
                ? 'Materializing'
                : panelState === 'healthy'
                  ? 'Healthy'
                  : 'Waiting for the first refresh'

    const latestError = currentJob?.status === 'Failed' ? currentJob.error : savedQuery.latest_error

    // In a broken state the most urgent fact is how stale the data is, not just that runs fail.
    const lastGoodRunAt = latestCompletedJob?.last_run_at ?? lastRunAt
    const freshnessLine = lastGoodRunAt ? (
        <div className="text-sm text-secondary">
            {latestCompletedJob ? `${humanFriendlyNumber(latestCompletedJob.rows_materialized)} rows · ` : ''}
            {`refreshed ${humanFriendlyDetailedTime(lastGoodRunAt, 'MMMM DD, YYYY', 'h:mm A')}`}
            {latestCompletedJob && jobDurationSeconds(latestCompletedJob) !== null
                ? ` (took ${humanFriendlyDuration(jobDurationSeconds(latestCompletedJob) as number)})`
                : ''}
        </div>
    ) : null

    const showSyncNowButton = panelState !== 'running'
    const menuItems: JSX.Element[] = []
    if (kind !== 'endpoint') {
        menuItems.push(
            <DropdownMenuItem
                key="revert"
                variant="destructive"
                disabled={panelState === 'running'}
                onClick={() => {
                    LemonDialog.open({
                        title: 'Revert materialization',
                        maxWidth: '30rem',
                        description:
                            'This stops all future scheduled runs and removes the stored table. The query stays available as a regular view, and you can materialize it again at any time.',
                        primaryButton: {
                            status: 'danger',
                            children: 'Revert materialization',
                            onClick: () => revertMaterialization(viewId),
                        },
                        secondaryButton: {
                            children: 'Cancel',
                        },
                    })
                }}
            >
                Revert materialization
            </DropdownMenuItem>
        )
    }

    return (
        <div
            className={`rounded border p-4 flex flex-col gap-2 ${cardStyle}`}
            data-attr={panelState === 'suspended' ? 'materialization-suspended-banner' : 'materialization-status-card'}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-h-8">
                    {statusIcon}
                    <span className="text-sm font-semibold">{title}</span>
                </div>
                <div className="flex items-center gap-2">
                    {panelState === 'suspended' && (
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => resumeMaterialization()}
                            loading={resumingMaterialization}
                            disabledReason={accessReason || undefined}
                            tooltip="If the query keeps failing, it will pause again."
                        >
                            Resume
                        </LemonButton>
                    )}
                    {panelState === 'running' && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => cancelDataWarehouseSavedQuery(viewId)}
                            disabledReason={accessReason || undefined}
                        >
                            Cancel run
                        </LemonButton>
                    )}
                    {showSyncNowButton && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={startingMaterialization}
                            disabledReason={accessReason || undefined}
                            tooltip={
                                panelState === 'suspended'
                                    ? 'Runs once now, so you can check whether your fix works before resuming.'
                                    : undefined
                            }
                            onClick={() => {
                                setStartingMaterialization(true)
                                runDataWarehouseSavedQuery(viewId)
                            }}
                        >
                            {startingMaterialization ? 'Starting...' : 'Sync now'}
                        </LemonButton>
                    )}
                    {menuItems.length > 0 && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconEllipsis />}
                                        disabledReason={accessReason || undefined}
                                        aria-label="More actions"
                                    />
                                }
                            />
                            <DropdownMenuContent align="end" className="min-w-52">
                                {menuItems}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </div>
            </div>

            {panelState === 'running' && currentJob ? (
                <div className="flex flex-col gap-1">
                    {jobProgressPercent(currentJob) !== null && (
                        <LemonProgress
                            percent={jobProgressPercent(currentJob) as number}
                            strokeColor="var(--warning)"
                        />
                    )}
                    <div className="text-secondary text-sm">
                        {currentJob.rows_expected
                            ? `${humanFriendlyNumber(currentJob.rows_materialized)} of ~${humanFriendlyNumber(
                                  currentJob.rows_expected
                              )} rows`
                            : `Started ${humanFriendlyDetailedTime(currentJob.created_at, 'MMMM DD, YYYY', 'h:mm A')}`}
                    </div>
                    {freshnessLine}
                </div>
            ) : (
                freshnessLine
            )}

            {panelState === 'failing' && (
                <div className="flex flex-col gap-1 text-sm text-secondary">
                    {latestError && (
                        <Tooltip title={latestError} interactive>
                            <div className="font-mono text-xs line-clamp-2">{latestError}</div>
                        </Tooltip>
                    )}
                </div>
            )}

            {panelState === 'suspended' && suspension && (
                <div className="flex flex-col gap-1 text-sm text-secondary">
                    <div>
                        Paused {humanFriendlyDetailedTime(suspension.at, 'MMMM DD, YYYY', 'h:mm A')} after {threshold}{' '}
                        failed runs in a row. Fix the query, then resume.
                    </div>
                    {suspension.reason && (
                        <Tooltip title={suspension.reason} interactive>
                            <div className="font-mono text-xs line-clamp-2">{suspension.reason}</div>
                        </Tooltip>
                    )}
                </div>
            )}

            {panelState !== 'suspended' && (
                <div className="text-secondary text-sm flex items-center gap-1 flex-wrap">
                    <span>Refreshes</span>
                    {canEditSyncFrequency ? (
                        <LemonSelect
                            type="tertiary"
                            size="xsmall"
                            disabledReason={accessReason || undefined}
                            value={savedQuery.sync_frequency || 'never'}
                            onChange={(newValue) => {
                                if (newValue) {
                                    updateDataWarehouseSavedQuery({
                                        id: viewId,
                                        sync_frequency: newValue,
                                        types: [[]],
                                        lifecycle: 'update',
                                    })
                                }
                            }}
                            loading={updatingDataWarehouseSavedQuery}
                            options={SYNC_FREQUENCY_OPTIONS}
                        />
                    ) : (
                        <span>{syncFrequencyPhrase(savedQuery.sync_frequency) ?? 'manually only'}</span>
                    )}
                    {nextRunAt && savedQuery.sync_frequency && savedQuery.sync_frequency !== 'never' && (
                        <span>
                            · next run{' '}
                            {nextRunAt.isBefore(dayjs())
                                ? 'soon'
                                : humanFriendlyDetailedTime(nextRunAt, 'MMMM DD, YYYY', 'h:mm A')}
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}

export function MaterializationRunsTable({ viewId }: { viewId: string }): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId })
    const { dataModelingJobs, dataModelingJobsLoading, hasMoreJobsToLoad } = useValues(jobsLogic)
    const { loadOlderDataModelingJobs } = useActions(jobsLogic)
    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated

    const jobs = dataModelingJobs?.results || []

    return (
        <div className="flex flex-col gap-2">
            <LemonTable
                size="small"
                loading={dataModelingJobsLoading && !jobs.length}
                dataSource={jobs}
                columns={[
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        render: (_, job: DataModelingJob) => {
                            const statusToType: Record<string, LemonTagType> = {
                                Completed: 'success',
                                Failed: 'danger',
                                Running: 'warning',
                            }
                            const type = statusToType[job.status] || 'warning'
                            const progress = jobProgressPercent(job)

                            const tooltip =
                                job.status === 'Running' && progress !== null
                                    ? `${humanFriendlyNumber(job.rows_materialized)} of ~${humanFriendlyNumber(
                                          job.rows_expected as number
                                      )} rows`
                                    : job.error && job.status !== 'Completed'
                                      ? job.error
                                      : undefined

                            return tooltip ? (
                                <Tooltip title={tooltip} interactive>
                                    <LemonTag type={type}>{job.status}</LemonTag>
                                </Tooltip>
                            ) : (
                                <LemonTag type={type}>{job.status}</LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Started',
                        dataIndex: 'created_at',
                        render: (_, { created_at }: DataModelingJob) => humanFriendlyDetailedTime(created_at),
                    },
                    {
                        title: 'Duration',
                        align: 'right',
                        render: (_, job: DataModelingJob) => {
                            if (job.status === 'Running') {
                                const elapsed = (Date.now() - new Date(job.created_at).getTime()) / 1000
                                return elapsed > 0 ? humanFriendlyDuration(elapsed) : '~'
                            }
                            const duration = jobDurationSeconds(job)
                            return duration === null ? '~' : humanFriendlyDuration(duration)
                        },
                    },
                    {
                        title: 'Rows',
                        dataIndex: 'rows_materialized',
                        align: 'right',
                        render: (_, { rows_materialized, status }: DataModelingJob) =>
                            (status === 'Running' || status === 'Cancelled') && rows_materialized === 0
                                ? '~'
                                : humanFriendlyNumber(rows_materialized),
                    },
                ]}
                expandable={
                    jobs.length
                        ? {
                              expandedRowRender: (job: DataModelingJob) => (
                                  <div className="p-4">
                                      <LogsViewer
                                          logicKey={`data_modeling_run:${job.id}`}
                                          sourceType="data_modeling_run"
                                          sourceId={viewId}
                                          groupByInstanceId={false}
                                          hideDateFilter
                                          hideLevelsFilter
                                          hideInstanceIdColumn
                                          defaultFilters={{
                                              instanceId: job.workflow_run_id,
                                              dateFrom: dayjsUtcToTimezone(job.created_at, timezone).format(
                                                  'YYYY-MM-DD HH:mm:ss'
                                              ),
                                              dateTo: job.last_run_at
                                                  ? dayjsUtcToTimezone(job.last_run_at, timezone)
                                                        .add(1, 'hour')
                                                        .format('YYYY-MM-DD HH:mm:ss')
                                                  : undefined,
                                              levels: showDebugLogs ? ['DEBUG', ...LOG_LEVELS] : LOG_LEVELS,
                                          }}
                                      />
                                  </div>
                              ),
                              rowExpandable: () => true,
                              noIndent: true,
                          }
                        : undefined
                }
                nouns={['run', 'runs']}
                emptyState="No runs yet"
                footer={
                    hasMoreJobsToLoad && (
                        <div className="flex items-center m-2">
                            <LemonButton
                                center
                                fullWidth
                                onClick={() => loadOlderDataModelingJobs()}
                                loading={dataModelingJobsLoading}
                            >
                                Load older runs
                            </LemonButton>
                        </div>
                    )
                }
            />
        </div>
    )
}
