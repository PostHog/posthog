import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
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

import { AccessControlLevel, AccessControlResourceType, LogEntryLevel } from '~/types'

import { SERVING_ENGINE } from 'products/data_modeling/frontend/suspension'
import type { DataModelingJobApi } from 'products/data_warehouse/frontend/generated/api.schemas'
import { MaterializationLoading } from 'products/data_warehouse/frontend/shared/components/MaterializationLoading'
import { MaterializationRunActions } from 'products/data_warehouse/frontend/shared/components/MaterializationRunActions'
import { MaterializationRunError } from 'products/data_warehouse/frontend/shared/components/MaterializationRunError'

import { IncrementalConfigOptions } from '../editor/IncrementalConfigFields'
import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { DEFAULT_JOBS_PAGE_SIZE, materializationJobsLogic } from './materializationJobsLogic'
import { computeJobDuration, fullRefreshReasonCopy, jobLogsWindow } from './materializationJobUtils'
import {
    SyncFrequencySelect,
    SyncFrequencyValue,
    defaultCadenceWithin,
    modeDisabledReason,
} from './SyncFrequencySelect'

const STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    Completed: 'success',
    Failed: 'danger',
    Running: 'warning',
    Cancelled: 'muted',
    Skipped: 'muted',
}

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

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
    showRunActions?: boolean
    showStatusSummary?: boolean
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
                ? 'Materialization is currently running'
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
    showRunActions = true,
    showStatusSummary = true,
}: MaterializationStatusPanelProps): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId, kind })
    const {
        dataModelingJobs,
        dataModelingJobsLoading,
        jobsPage,
        jobsPageResults,
        olderJobsPageLoading,
        olderJobsPageError,
        dataModelingJobsError,
        lastSuccessfulSyncAt,
        startingMaterialization,
        savedQuery,
        savedQueryLoading,
        initialSyncFrequency,
        incrementalCheck,
        incrementalDraft,
        syncFrequencyDraft,
        savingMaterialization,
    } = useValues(jobsLogic)
    const {
        loadDataModelingJobs,
        setJobsPage,
        loadOlderJobsPage,
        setInitialSyncFrequency,
        setIncrementalDraft,
        setSyncFrequencyDraft,
    } = useActions(jobsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { updatingDataWarehouseSavedQuery, materializationActionLoading } = useValues(dataWarehouseViewsLogic)

    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated
    const materializationAccessReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor,
        savedQuery?.user_access_level
    )

    if (!savedQuery) {
        return (
            <div className="min-h-64" data-attr="materialization-status-panel">
                {savedQueryLoading ? <MaterializationLoading /> : null}
            </div>
        )
    }

    const currentJobStatus = dataModelingJobs?.results?.[0]?.status || null
    const { sync } = getMaterializationDisabledReasons(currentJobStatus, startingMaterialization)
    const incrementalFlagOn = kind !== 'endpoint' && !!featureFlags[FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]
    const showIncremental = incrementalFlagOn && !!savedQuery.incremental?.enabled
    const lastRunMode = savedQuery.incremental_state?.last_run_mode
    // The saved query records the mode of the last run that finished, so the reason comes from the
    // newest run that recorded one rather than from whatever run is at the top of the list.
    const lastRunFullRefreshReason = fullRefreshReasonCopy(
        dataModelingJobs?.results?.find((job) => job.full_refresh_reason)?.full_refresh_reason
    )
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
    const cadenceOwnedElsewhere = modeDisabledReason(savedQuery.sync_frequency_bounds)
    const isPaused = !cadenceOwnedElsewhere && (!savedQuery.sync_frequency || savedQuery.sync_frequency === 'never')

    // Only ClickHouse serves queries, so a marker on a shadow engine means the comparison
    // run stopped, not that this model stopped refreshing.
    const suspension = savedQuery.suspended?.[SERVING_ENGINE]
    const showSuspendedBanner = !!suspension && !!savedQuery.is_materialized

    return (
        <div className="@container/materialization" data-attr="materialization-status-panel">
            <div className="flex flex-col flex-1 gap-4">
                <div>
                    <div className="flex flex-row items-center gap-2">
                        {!hideTitle && (
                            <>
                                <h3 className="mb-0">Materialization</h3>
                                <LemonTag type="warning">BETA</LemonTag>
                            </>
                        )}
                        {showStatusSummary && savedQuery?.latest_error && savedQuery.status === 'Failed' && (
                            <Tooltip title={savedQuery.latest_error} interactive>
                                <LemonTag type="danger">Error</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    {showStatusSummary && showSuspendedBanner && suspension && (
                        <LemonBanner type="error" className="mt-2">
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
                                {showStatusSummary && (
                                    <LemonCard hoverEffect={false} className="!p-3 mb-4 w-fit max-w-full">
                                        <div className="flex flex-wrap items-center gap-2 mb-2">
                                            <span className="font-semibold">
                                                {currentJobStatus === 'Running' ? 'Current run' : 'Last run'}
                                            </span>
                                            {currentJobStatus ? (
                                                <LemonTag type={STATUS_TAG_TYPES[currentJobStatus] ?? 'default'}>
                                                    {currentJobStatus === 'Cancelled' ? 'Canceled' : currentJobStatus}
                                                </LemonTag>
                                            ) : dataModelingJobsLoading ? (
                                                <LemonSkeleton className="h-5 w-20" />
                                            ) : (
                                                <LemonTag type="muted">
                                                    {dataModelingJobs ? 'Not run yet' : 'Status unavailable'}
                                                </LemonTag>
                                            )}
                                        </div>
                                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                                            <span className="text-secondary">Last successful refresh</span>
                                            {lastSuccessfulSyncAt ? (
                                                <TZLabel time={lastSuccessfulSyncAt} />
                                            ) : dataModelingJobsLoading ? (
                                                <LemonSkeleton className="h-4 w-24" />
                                            ) : (
                                                <span>
                                                    {dataModelingJobs
                                                        ? 'No successful run in recent history'
                                                        : 'Run history unavailable'}
                                                </span>
                                            )}
                                        </div>
                                    </LemonCard>
                                )}
                                {showIncremental && lastRunMode === 'incremental' && (
                                    <div className="text-xs text-secondary mt-1">
                                        Updating new rows only, up to{' '}
                                        {formatWatermark(savedQuery.incremental_state?.watermark)}
                                    </div>
                                )}
                                {showIncremental && lastRunMode === 'full_refresh' && lastRunFullRefreshReason && (
                                    <div className="text-xs text-secondary mt-1">
                                        <span>Rebuilt the whole table.&nbsp;</span>
                                        <span>{lastRunFullRefreshReason.explanation}</span>
                                    </div>
                                )}
                                {showStatusSummary && isPaused && kind !== 'endpoint' && (
                                    <div className="text-xs text-secondary mt-1">
                                        Scheduled refreshes are paused. Pick a cadence to resume, or use Sync now to
                                        refresh it once.
                                    </div>
                                )}
                                <div className="flex flex-col gap-2 items-start mt-2">
                                    {kind !== 'endpoint' && (
                                        <SyncFrequencySelect
                                            bounds={savedQuery.sync_frequency_bounds}
                                            disabledReason={
                                                sync ||
                                                (savingMaterialization
                                                    ? 'Saving materialization settings'
                                                    : undefined) ||
                                                materializationAccessReason ||
                                                (materializationActionLoading ? 'Updating materialization' : undefined)
                                            }
                                            value={
                                                syncFrequencyDraft ??
                                                (savedQuery.sync_frequency as SyncFrequencyValue) ??
                                                'never'
                                            }
                                            onChange={setSyncFrequencyDraft}
                                            loading={updatingDataWarehouseSavedQuery || materializationActionLoading}
                                        />
                                    )}
                                    {showRunActions && (
                                        <div className="flex flex-wrap items-center gap-2">
                                            <MaterializationRunActions viewId={viewId} kind={kind} />
                                        </div>
                                    )}
                                </div>
                                {incrementalFlagOn && !savedQuery.managed_viewset_kind && incrementalCheck && (
                                    <fieldset
                                        className="mt-4 max-w-160"
                                        disabled={
                                            !!(
                                                sync ||
                                                savingMaterialization ||
                                                materializationAccessReason ||
                                                materializationActionLoading
                                            )
                                        }
                                    >
                                        <h4 className="mb-0">Refresh mode</h4>
                                        <IncrementalConfigOptions
                                            check={incrementalCheck}
                                            draft={incrementalDraft}
                                            onChange={setIncrementalDraft}
                                        />
                                        {refreshModeChanged && incrementalDraft.enabled && (
                                            <div className="mt-2">
                                                <div className="text-xs text-secondary mt-1">
                                                    {structuralChange
                                                        ? 'Changing these settings rebuilds the whole table on the next run. After that, runs update only new rows.'
                                                        : 'The new lookback applies from the next run.'}
                                                </div>
                                            </div>
                                        )}
                                    </fieldset>
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
                                            disabledReason={
                                                materializationAccessReason ||
                                                (materializationActionLoading ? 'Updating materialization' : undefined)
                                            }
                                            value={startingFrequency}
                                            onChange={(newValue) => setInitialSyncFrequency(newValue)}
                                        />
                                    )}
                                    {showRunActions && <MaterializationRunActions viewId={viewId} kind={kind} />}
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
                <div className="border-t pt-6 mt-4 flex items-start justify-between gap-2">
                    <div>
                        <h3 className="mb-0">Run history</h3>
                    </div>
                    <LemonButton
                        icon={<IconRefresh />}
                        size="small"
                        type="secondary"
                        onClick={() => (jobsPage === 1 ? loadDataModelingJobs() : loadOlderJobsPage())}
                        loading={jobsPage === 1 ? dataModelingJobsLoading : olderJobsPageLoading}
                        disabledReason={startingMaterialization ? 'Materialization is starting' : undefined}
                        tooltip="Refresh runs"
                        aria-label="Refresh runs"
                    />
                </div>
                {(jobsPage === 1 ? dataModelingJobsError : olderJobsPageError) && (
                    <LemonBanner type="error">Couldn't load runs. Use Refresh runs to try again.</LemonBanner>
                )}
                <LemonTable
                    rowKey="id"
                    pagination={{
                        controlled: true,
                        useUrl: false,
                        pageSize: DEFAULT_JOBS_PAGE_SIZE,
                        currentPage: jobsPage,
                        entryCount: jobsPageResults?.count,
                        // PaginationControl decides whether an arrow is enabled from the entry count, not
                        // from these handlers, so withholding one while a page loads would leave a live
                        // arrow that does nothing. Let the click through: the page loader breakpoints, so
                        // the superseded response is discarded.
                        onBackward: jobsPage > 1 ? () => setJobsPage(jobsPage - 1) : undefined,
                        onForward: jobsPageResults?.next ? () => setJobsPage(jobsPage + 1) : undefined,
                    }}
                    size="small"
                    // A timer reloads page 1 in the background, and LemonTable's loading overlay blocks
                    // pointer events over the rows and the pager, so page 1 shows the loader only before it
                    // has rows. Only a user action loads an older page, so that loader always shows.
                    loading={
                        jobsPage === 1
                            ? dataModelingJobsLoading && !jobsPageResults?.results?.length
                            : olderJobsPageLoading
                    }
                    dataSource={jobsPage > 1 && olderJobsPageError ? [] : jobsPageResults?.results || []}
                    columns={[
                        {
                            title: 'Status',
                            dataIndex: 'status',
                            render: (_, job: DataModelingJobApi) => {
                                const { status, rows_materialized, rows_expected } = job
                                const type = STATUS_TAG_TYPES[status] || 'warning'

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

                                return <LemonTag type={type}>{status}</LemonTag>
                            },
                        },
                        {
                            title: 'Refresh mode',
                            dataIndex: 'run_mode',
                            isHidden:
                                !showIncremental || !savedQuery.is_materialized || !jobsPageResults?.results?.length,
                            render: (_, { run_mode, full_refresh_reason }: DataModelingJobApi) => {
                                if (run_mode === 'incremental') {
                                    return 'Incremental'
                                }
                                if (run_mode !== 'full_refresh') {
                                    return '-'
                                }
                                const reason = fullRefreshReasonCopy(full_refresh_reason)
                                if (!reason) {
                                    return 'Full refresh'
                                }
                                return (
                                    <Tooltip title={reason.explanation}>
                                        <div>
                                            <div>Full refresh</div>
                                            <div className="text-xs text-secondary">{reason.label}</div>
                                        </div>
                                    </Tooltip>
                                )
                            },
                        },
                        {
                            title: 'Error',
                            dataIndex: 'error',
                            render: (_, { error, status }: DataModelingJobApi) => (
                                <div className="max-w-28 @min-[48rem]/materialization:max-w-60">
                                    <span
                                        className={`block truncate ${status === 'Failed' ? 'text-danger' : 'text-secondary'}`}
                                    >
                                        {error?.split('\n')[0]}
                                    </span>
                                </div>
                            ),
                        },
                        {
                            title: 'Rows',
                            dataIndex: 'rows_materialized',
                            render: (_, { rows_materialized, status, run_mode }: DataModelingJobApi) => {
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
                            render: (_, { last_run_at }: DataModelingJobApi) =>
                                last_run_at ? <TZLabel time={last_run_at} /> : '-',
                        },
                        {
                            title: 'Duration',
                            render: (_, job: DataModelingJobApi) => computeJobDuration(job),
                        },
                    ]}
                    expandable={
                        jobsPageResults?.results?.length
                            ? {
                                  expandedRowRender: (job: DataModelingJobApi) => (
                                      <div className="p-4 min-w-0">
                                          <MaterializationRunError error={job.error} status={job.status} />
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
                />
            </div>
        </div>
    )
}
