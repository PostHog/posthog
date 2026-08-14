import { useActions, useValues } from 'kea'

import { IconRefresh, IconRevert, IconX } from '@posthog/icons'
import { LemonBanner, LemonDialog, LemonTable, Link, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, DataModelingJob, LogEntryLevel } from '~/types'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { materializationJobsLogic } from './materializationJobsLogic'
import { computeJobDuration, jobLogsWindow } from './materializationJobUtils'
import {
    SyncFrequencySelect,
    SyncFrequencyValue,
    defaultCadenceWithin,
    modeDisabledReason,
    unsatisfiableReason,
} from './SyncFrequencySelect'

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

// Matches DataModelingJobEngine.CLICKHOUSE, the engine materialized queries are served from.
const SERVING_ENGINE = 'clickhouse'

interface MaterializationStatusPanelProps {
    viewId: string
    /**
     * The product surface this panel is rendered in. Endpoints own the materialization lifecycle of their
     * backing saved query, so destructive saved-query controls (revert, sync frequency) must be hidden
     * when `kind === 'endpoint'` — those mutations bypass the endpoint's `_disable_materialization` flow.
     */
    kind?: 'view' | 'endpoint'
}

function getMaterializationStatusMessage(
    rowsMaterialized: number,
    progressPercentage: number,
    rowsExpected: number
): string {
    const percentComplete = Math.round(Math.min(100, (rowsMaterialized / rowsExpected) * 100))
    switch (true) {
        case rowsMaterialized === 0:
            return `Spinning up spikes — starting materialization job... ${percentComplete}% complete.`
        case progressPercentage < 10:
            return `Digging into SQL... executing your query now... ${percentComplete}% complete.`
        case progressPercentage < 25:
            return `First ${humanFriendlyNumber(rowsMaterialized)} rows tucked away... ${percentComplete}% complete.`
        case progressPercentage < 50:
            return `${humanFriendlyNumber(rowsMaterialized)} rows shipped to storage... ${percentComplete}% complete.`
        case progressPercentage < 90:
            return `Still going — ${humanFriendlyNumber(
                rowsMaterialized
            )} rows written... ${percentComplete}% complete.`
        case progressPercentage === 100:
            return `Wrapping up — ${humanFriendlyNumber(
                rowsMaterialized
            )} rows processed... ${percentComplete}% complete.`
        default:
            return `Almost there — ${humanFriendlyNumber(
                rowsMaterialized
            )} rows processed... ${percentComplete}% complete.`
    }
}

function getMaterializationDisabledReasons(
    currentJobStatus: string | null,
    startingMaterialization: boolean
): {
    sync: string | false
    cancel: string | false
    revert: string | false
} {
    return {
        sync:
            currentJobStatus === 'Running'
                ? 'Materialization is already running'
                : startingMaterialization
                  ? 'Materialization is starting'
                  : false,
        cancel: currentJobStatus !== 'Running' ? 'Materialization is not running' : false,
        revert: currentJobStatus === 'Running' ? 'Cannot revert while materialization is running' : false,
    }
}

export function MaterializationStatusPanel({ viewId, kind = 'view' }: MaterializationStatusPanelProps): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId })
    const {
        dataModelingJobs,
        dataModelingJobsLoading,
        hasMoreJobsToLoad,
        startingMaterialization,
        resumingMaterialization,
        savedQuery,
        savedQueryLoading,
        initialSyncFrequency,
    } = useValues(jobsLogic)
    const {
        loadDataModelingJobs,
        loadOlderDataModelingJobs,
        setStartingMaterialization,
        resumeMaterialization,
        setInitialSyncFrequency,
    } = useActions(jobsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const {
        updateDataWarehouseSavedQuery,
        runDataWarehouseSavedQuery,
        cancelDataWarehouseSavedQuery,
        materializeDataWarehouseSavedQuery,
        revertMaterialization,
    } = useActions(dataWarehouseViewsLogic)

    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated
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

    const currentJobStatus = dataModelingJobs?.results?.[0]?.status || null
    const { sync, cancel, revert } = getMaterializationDisabledReasons(currentJobStatus, startingMaterialization)
    const startingFrequency = defaultCadenceWithin(savedQuery.sync_frequency_bounds, initialSyncFrequency)
    const noCadenceReason = unsatisfiableReason(savedQuery.sync_frequency_bounds)
    const isPaused = !savedQuery.sync_frequency || savedQuery.sync_frequency === 'never'

    // Prefer the serving engine's entry when several engines are suspended.
    const suspension = savedQuery.suspended
        ? (savedQuery.suspended[SERVING_ENGINE] ?? Object.values(savedQuery.suspended)[0])
        : undefined
    const showSuspendedBanner =
        !!featureFlags[FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES] &&
        !!suspension &&
        !!savedQuery.is_materialized

    return (
        <div className="overflow-auto" data-attr="materialization-status-panel">
            <div className="flex flex-col flex-1 gap-4">
                <div>
                    <div className="flex flex-row items-center gap-2">
                        <h3 className="mb-0">Materialization</h3>
                        <LemonTag type="warning">BETA</LemonTag>
                        {savedQuery?.latest_error && savedQuery.status === 'Failed' && (
                            <Tooltip title={savedQuery.latest_error} interactive>
                                <LemonTag type="danger">Error</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    {showSuspendedBanner && suspension && (
                        <LemonBanner
                            type="error"
                            className="mt-2"
                            action={{
                                children: 'Resume',
                                onClick: () => resumeMaterialization(),
                                loading: resumingMaterialization,
                                disabledReason: materializationAccessReason || undefined,
                                tooltip: 'If the query keeps failing, it will pause again.',
                            }}
                        >
                            <div data-attr="materialization-suspended-banner">
                                <div>
                                    Scheduled runs are paused for this {kind === 'endpoint' ? 'endpoint' : 'view'}{' '}
                                    because materialization kept failing. Fix the query, then resume.
                                </div>
                                <Tooltip title={suspension.reason} interactive>
                                    <div className="mt-1 text-xs font-normal line-clamp-2">
                                        Paused {humanFriendlyDetailedTime(suspension.at)} · {suspension.reason}
                                    </div>
                                </Tooltip>
                            </div>
                        </LemonBanner>
                    )}
                    <div>
                        {savedQuery?.is_materialized ? (
                            <div>
                                {savedQuery?.last_run_at ? (
                                    `Last run at ${humanFriendlyDetailedTime(savedQuery?.last_run_at)}`
                                ) : showSuspendedBanner ? null : (
                                    <div>
                                        <span>Materialization scheduled</span>
                                    </div>
                                )}
                                <div className="flex flex-col gap-2 items-start mt-2">
                                    {kind !== 'endpoint' && (
                                        <SyncFrequencySelect
                                            bounds={savedQuery.sync_frequency_bounds}
                                            disabledReason={sync || materializationAccessReason || undefined}
                                            value={(savedQuery.sync_frequency as SyncFrequencyValue) || 'never'}
                                            onChange={(newValue) =>
                                                updateDataWarehouseSavedQuery({
                                                    id: viewId,
                                                    sync_frequency: newValue,
                                                    types: [[]],
                                                    lifecycle: 'update',
                                                })
                                            }
                                            loading={updatingDataWarehouseSavedQuery}
                                        />
                                    )}
                                    <div className="flex items-center gap-2">
                                        <LemonButton
                                            className="whitespace-nowrap"
                                            size="small"
                                            loading={startingMaterialization || currentJobStatus === 'Running'}
                                            disabledReason={sync || materializationAccessReason}
                                            onClick={() => {
                                                setStartingMaterialization(true)
                                                runDataWarehouseSavedQuery(viewId)
                                            }}
                                            type="secondary"
                                            sideAction={{
                                                icon: <IconX fontSize={16} />,
                                                tooltip: 'Cancel materialization',
                                                onClick: () => cancelDataWarehouseSavedQuery(viewId),
                                                disabledReason: cancel || materializationAccessReason || undefined,
                                            }}
                                        >
                                            {startingMaterialization
                                                ? 'Starting...'
                                                : currentJobStatus === 'Running'
                                                  ? 'Running...'
                                                  : 'Sync now'}
                                        </LemonButton>
                                        {kind !== 'endpoint' && (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                tooltip="Stop refreshing on a schedule. The table stays, holding what it last loaded."
                                                disabledReason={
                                                    materializationAccessReason ||
                                                    modeDisabledReason(savedQuery.sync_frequency_bounds) ||
                                                    (isPaused ? 'Already paused. Pick a cadence to resume.' : undefined)
                                                }
                                                loading={updatingDataWarehouseSavedQuery}
                                                onClick={() =>
                                                    updateDataWarehouseSavedQuery({
                                                        id: viewId,
                                                        sync_frequency: 'never',
                                                        types: [[]],
                                                        lifecycle: 'update',
                                                    })
                                                }
                                            >
                                                Pause refreshes
                                            </LemonButton>
                                        )}
                                        {kind !== 'endpoint' && (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                tooltip="Revert materialized view to view"
                                                disabledReason={revert || materializationAccessReason}
                                                icon={<IconRevert />}
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Revert materialization',
                                                        maxWidth: '30rem',
                                                        description:
                                                            'Are you sure you want to revert this materialized view to a regular view? This will stop all future materializations and remove the materialized table. You will always be able to go back to a materialized view at any time.',
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
                                            />
                                        )}
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div>
                                <p className="text-xs">
                                    Materialized views are a way to pre-compute data in your data warehouse. This allows
                                    you to run queries faster and more efficiently.
                                    <br />
                                    <Link
                                        data-attr="materializing-help"
                                        to="https://posthog.com/docs/data-warehouse/views#materializing-and-scheduling-a-view"
                                        target="_blank"
                                    >
                                        Learn more about materialization
                                    </Link>
                                    .
                                </p>
                                <div className="flex flex-col gap-2 items-start">
                                    {kind !== 'endpoint' && (
                                        <SyncFrequencySelect
                                            data-attr="initial-sync-frequency"
                                            bounds={savedQuery.sync_frequency_bounds}
                                            disabledReason={materializationAccessReason || undefined}
                                            value={startingFrequency}
                                            onChange={(newValue) => setInitialSyncFrequency(newValue)}
                                        />
                                    )}
                                    <LemonButton
                                        size="small"
                                        onClick={() => materializeDataWarehouseSavedQuery(viewId, startingFrequency)}
                                        type="primary"
                                        loading={updatingDataWarehouseSavedQuery}
                                        disabledReason={materializationAccessReason || noCadenceReason}
                                    >
                                        Materialize
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex items-start justify-between">
                    <div>
                        <h3>Materialization Runs</h3>
                        <p className="text-xs">
                            The last runs for this materialized view. These can be scheduled or run on demand.
                        </p>
                    </div>
                    <LemonButton
                        icon={<IconRefresh />}
                        size="small"
                        type="secondary"
                        onClick={() => loadDataModelingJobs()}
                        loading={dataModelingJobsLoading}
                        disabledReason={startingMaterialization ? 'Materialization is starting' : undefined}
                        tooltip="Refresh runs"
                    />
                </div>
                <LemonTable
                    size="small"
                    loading={dataModelingJobsLoading && !dataModelingJobs?.results?.length}
                    dataSource={dataModelingJobs?.results || []}
                    columns={[
                        {
                            title: 'Status',
                            dataIndex: 'status',
                            render: (_, job: DataModelingJob) => {
                                const { status, error, rows_materialized, rows_expected } = job
                                const statusToType: Record<string, LemonTagType> = {
                                    Completed: 'success',
                                    Failed: 'danger',
                                    Running: 'warning',
                                    Skipped: 'muted',
                                }
                                const type = statusToType[status] || 'warning'

                                const progressPercentage =
                                    rows_expected && rows_expected > 0
                                        ? Math.min(100, (rows_materialized / rows_expected) * 100)
                                        : 0

                                if (status === 'Running' && progressPercentage > 0 && rows_expected !== null) {
                                    return (
                                        <Tooltip
                                            placement="right"
                                            title={getMaterializationStatusMessage(
                                                rows_materialized,
                                                progressPercentage,
                                                rows_expected
                                            )}
                                        >
                                            <div className="w-[68px]">
                                                <LemonProgress percent={progressPercentage} />
                                            </div>
                                        </Tooltip>
                                    )
                                }

                                return error && status !== 'Completed' ? (
                                    <Tooltip title={error} interactive>
                                        <LemonTag type={type}>{status}</LemonTag>
                                    </Tooltip>
                                ) : (
                                    <LemonTag type={type}>{status}</LemonTag>
                                )
                            },
                        },
                        {
                            title: 'Rows',
                            dataIndex: 'rows_materialized',
                            render: (_, { rows_materialized, status }: DataModelingJob) =>
                                (status === 'Running' || status === 'Cancelled' || status === 'Skipped') &&
                                rows_materialized === 0
                                    ? '~'
                                    : humanFriendlyNumber(rows_materialized),
                        },
                        {
                            title: 'Updated',
                            dataIndex: 'last_run_at',
                            render: (_, { last_run_at }: DataModelingJob) =>
                                last_run_at ? humanFriendlyDetailedTime(last_run_at) : '-',
                        },
                        {
                            title: 'Duration',
                            render: (_, job: DataModelingJob) => computeJobDuration(job),
                        },
                    ]}
                    expandable={
                        dataModelingJobs?.results?.length
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
                                                  instanceId: job.workflow_run_id ?? undefined,
                                                  ...jobLogsWindow(job, timezone),
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
                    emptyState="No runs available"
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
        </div>
    )
}
