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

import { IncrementalConfigOptions } from '../editor/IncrementalConfigFields'
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
    /** Drops the "Materialization" heading where the surface already names the panel, such as a tab. */
    hideTitle?: boolean
}

// Watermarks are only ISO strings for date/datetime incremental keys. Numeric and arbitrary
// string keys must render as-is: pushing them through a date formatter shows a bogus timestamp.
const ISO_DATE_PREFIX = /^\d{4}-\d{2}-\d{2}([T ]|$)/

function formatWatermark(watermark: string | null | undefined): string {
    if (watermark == null || watermark === '') {
        return 'the last run'
    }
    return ISO_DATE_PREFIX.test(watermark) ? humanFriendlyDetailedTime(watermark) : watermark
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

export function MaterializationStatusPanel({
    viewId,
    kind = 'view',
    hideTitle,
}: MaterializationStatusPanelProps): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId, kind })
    const {
        dataModelingJobs,
        dataModelingJobsLoading,
        hasMoreJobsToLoad,
        startingMaterialization,
        resumingMaterialization,
        savedQuery,
        savedQueryLoading,
        initialSyncFrequency,
        incrementalCheck,
        incrementalDraft,
    } = useValues(jobsLogic)
    const {
        loadDataModelingJobs,
        loadOlderDataModelingJobs,
        setStartingMaterialization,
        resumeMaterialization,
        setInitialSyncFrequency,
        setIncrementalDraft,
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
    const incrementalFlagOn = kind !== 'endpoint' && !!featureFlags[FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]
    const showIncremental = incrementalFlagOn && !!savedQuery.incremental?.enabled
    const lastRunMode = savedQuery.incremental_state?.last_run_mode
    // Blocks the Materialize/save buttons while the incremental picks are incomplete, mirroring
    // the save-as-view form's validation.
    const incrementalDraftError = !incrementalDraft.enabled
        ? undefined
        : !incrementalDraft.incrementalKey
          ? 'Select the incremental column'
          : incrementalDraft.uniqueKey.length === 0
            ? 'Select at least one unique key column'
            : undefined
    const savedIncremental = savedQuery.incremental
    // Key or unique-key edits change what the stored rows mean, so the next run rebuilds (via the
    // definition fingerprint). A lookback-only change is operational and does not.
    const structuralChange = savedIncremental?.enabled
        ? !incrementalDraft.enabled ||
          incrementalDraft.incrementalKey !== savedIncremental.incremental_key ||
          [...incrementalDraft.uniqueKey].sort().join(',') !== [...savedIncremental.unique_key].sort().join(',')
        : incrementalDraft.enabled
    const lookbackChanged =
        !!savedIncremental?.enabled &&
        incrementalDraft.enabled &&
        incrementalDraft.lookbackSeconds !== (savedIncremental.lookback_seconds ?? 0)
    const refreshModeChanged = structuralChange || lookbackChanged
    const startingFrequency = defaultCadenceWithin(savedQuery.sync_frequency_bounds, initialSyncFrequency)
    const noCadenceReason = unsatisfiableReason(savedQuery.sync_frequency_bounds)
    const cadenceOwnedElsewhere = modeDisabledReason(savedQuery.sync_frequency_bounds)
    const isPaused = !cadenceOwnedElsewhere && (!savedQuery.sync_frequency || savedQuery.sync_frequency === 'never')

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
                        {!hideTitle && <h3 className="mb-0">Materialization</h3>}
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
                                {showIncremental && (
                                    <div className="text-xs text-secondary mt-1">
                                        {lastRunMode === 'incremental'
                                            ? `Updating new rows only, up to ${formatWatermark(
                                                  savedQuery.incremental_state?.watermark
                                              )}`
                                            : 'The last run rebuilt the whole table. The next one will update only new rows.'}
                                    </div>
                                )}
                                {isPaused && kind !== 'endpoint' && (
                                    <div className="text-xs text-secondary mt-1">
                                        Scheduled refreshes are paused. Pick a cadence to resume, or use Sync now to
                                        refresh it once.
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
                                        {showIncremental && (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                tooltip="Rebuild the whole table from scratch instead of updating it"
                                                disabledReason={sync || materializationAccessReason}
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Rebuild this table',
                                                        maxWidth: '30rem',
                                                        description:
                                                            'This runs the query over all of your data and replaces the table, instead of updating only new rows. It takes as long as the first materialization did. Use it after correcting upstream data.',
                                                        primaryButton: {
                                                            children: 'Rebuild',
                                                            onClick: () => {
                                                                setStartingMaterialization(true)
                                                                runDataWarehouseSavedQuery(viewId, true)
                                                            },
                                                        },
                                                        secondaryButton: { children: 'Cancel' },
                                                    })
                                                }}
                                            >
                                                Rebuild
                                            </LemonButton>
                                        )}
                                        {kind !== 'endpoint' && (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                tooltip="Stop refreshing on a schedule. The table stays, holding what it last loaded."
                                                disabledReason={
                                                    materializationAccessReason ||
                                                    cadenceOwnedElsewhere ||
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
                                {incrementalFlagOn && !savedQuery.managed_viewset_kind && (
                                    <div className="mt-4 max-w-160">
                                        <h4 className="mb-0">Refresh mode</h4>
                                        <IncrementalConfigOptions
                                            check={incrementalCheck}
                                            draft={incrementalDraft}
                                            onChange={setIncrementalDraft}
                                        />
                                        {refreshModeChanged && (
                                            <div className="mt-2">
                                                <LemonButton
                                                    type="primary"
                                                    size="small"
                                                    loading={updatingDataWarehouseSavedQuery}
                                                    disabledReason={
                                                        materializationAccessReason || incrementalDraftError || sync
                                                    }
                                                    onClick={() =>
                                                        updateDataWarehouseSavedQuery({
                                                            id: viewId,
                                                            incremental:
                                                                incrementalDraft.enabled &&
                                                                incrementalDraft.incrementalKey
                                                                    ? {
                                                                          enabled: true,
                                                                          incremental_key:
                                                                              incrementalDraft.incrementalKey,
                                                                          unique_key: incrementalDraft.uniqueKey,
                                                                          lookback_seconds:
                                                                              incrementalDraft.lookbackSeconds,
                                                                      }
                                                                    : null,
                                                            types: [[]],
                                                            lifecycle: 'update',
                                                        })
                                                    }
                                                >
                                                    Save refresh mode
                                                </LemonButton>
                                                <div className="text-xs text-secondary mt-1">
                                                    {!incrementalDraft.enabled
                                                        ? 'Every run will rebuild the whole table.'
                                                        : structuralChange
                                                          ? 'Changing these settings rebuilds the whole table on the next run. After that, runs update only new rows.'
                                                          : 'The new lookback applies from the next run.'}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
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
                                        onClick={() =>
                                            materializeDataWarehouseSavedQuery(
                                                viewId,
                                                startingFrequency,
                                                incrementalDraft.enabled && incrementalDraft.incrementalKey
                                                    ? {
                                                          enabled: true,
                                                          incremental_key: incrementalDraft.incrementalKey,
                                                          unique_key: incrementalDraft.uniqueKey,
                                                          lookback_seconds: incrementalDraft.lookbackSeconds,
                                                      }
                                                    : undefined
                                            )
                                        }
                                        type="primary"
                                        loading={updatingDataWarehouseSavedQuery}
                                        disabledReason={
                                            materializationAccessReason || noCadenceReason || incrementalDraftError
                                        }
                                    >
                                        Materialize
                                    </LemonButton>
                                </div>
                                {incrementalFlagOn && (
                                    <div className="max-w-160">
                                        <IncrementalConfigOptions
                                            check={incrementalCheck}
                                            draft={incrementalDraft}
                                            onChange={setIncrementalDraft}
                                        />
                                    </div>
                                )}
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

                                const statusTag =
                                    error && status !== 'Completed' ? (
                                        <Tooltip title={error} interactive>
                                            <LemonTag type={type}>{status}</LemonTag>
                                        </Tooltip>
                                    ) : (
                                        <LemonTag type={type}>{status}</LemonTag>
                                    )
                                return (
                                    <div className="flex items-center gap-1">
                                        {statusTag}
                                        {showIncremental && job.run_mode && (
                                            <LemonTag type="muted">
                                                {job.run_mode === 'incremental' ? 'incremental' : 'full refresh'}
                                            </LemonTag>
                                        )}
                                    </div>
                                )
                            },
                        },
                        {
                            title: 'Rows',
                            dataIndex: 'rows_materialized',
                            render: (_, { rows_materialized, status, run_mode }: DataModelingJob) => {
                                if (
                                    (status === 'Running' || status === 'Cancelled' || status === 'Skipped') &&
                                    rows_materialized === 0
                                ) {
                                    return '~'
                                }
                                const count = humanFriendlyNumber(rows_materialized)
                                if (!run_mode) {
                                    return count
                                }
                                return (
                                    <Tooltip
                                        title={
                                            run_mode === 'incremental'
                                                ? 'Rows this run synced, including the re-read lookback window.'
                                                : 'This run rebuilt the whole table. This is its full row count.'
                                        }
                                    >
                                        <span>{count}</span>
                                    </Tooltip>
                                )
                            },
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
