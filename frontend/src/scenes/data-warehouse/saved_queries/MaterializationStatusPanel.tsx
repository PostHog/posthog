import { useActions, useValues } from 'kea'

import { IconRefresh, IconRevert, IconX } from '@posthog/icons'
import { LemonDialog, LemonTable, Link, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjsUtcToTimezone } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDetailedTime, humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlLevel,
    AccessControlResourceType,
    DataModelingJob,
    DataModelingSyncInterval,
    LogEntryLevel,
    OrNever,
} from '~/types'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { materializationJobsLogic } from './materializationJobsLogic'

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

const SYNC_FREQUENCY_OPTIONS = [
    {
        value: 'never' as OrNever,
        label: ' No resync',
    },
    {
        value: '15min' as DataModelingSyncInterval,
        label: ' Resync every 15 mins',
    },
    {
        value: '30min' as DataModelingSyncInterval,
        label: ' Resync every 30 mins',
    },
    {
        value: '1hour' as DataModelingSyncInterval,
        label: ' Resync every 1 hour',
    },
    {
        value: '6hour' as DataModelingSyncInterval,
        label: ' Resync every 6 hours',
    },
    {
        value: '12hour' as DataModelingSyncInterval,
        label: ' Resync every 12 hours',
    },
    {
        value: '24hour' as DataModelingSyncInterval,
        label: ' Resync Daily',
    },
    {
        value: '7day' as DataModelingSyncInterval,
        label: ' Resync Weekly',
    },
    {
        value: '30day' as DataModelingSyncInterval,
        label: ' Resync Monthly',
    },
]

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
        savedQuery,
        savedQueryLoading,
    } = useValues(jobsLogic)
    const { loadDataModelingJobs, loadOlderDataModelingJobs, setStartingMaterialization } = useActions(jobsLogic)

    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const {
        updateDataWarehouseSavedQuery,
        runDataWarehouseSavedQuery,
        cancelDataWarehouseSavedQuery,
        materializeDataWarehouseSavedQuery,
        revertMaterialization,
    } = useActions(dataWarehouseViewsLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated
    const isDagSchedulesOnly = !!featureFlags[FEATURE_FLAGS.DATA_MODELING_BACKEND_V2]
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
                    <div>
                        {savedQuery?.is_materialized ? (
                            <div>
                                {savedQuery?.last_run_at ? (
                                    `Last run at ${humanFriendlyDetailedTime(savedQuery?.last_run_at)}`
                                ) : (
                                    <div>
                                        <span>Materialization scheduled</span>
                                    </div>
                                )}
                                <div className="flex gap-4 mt-2">
                                    <LemonButton
                                        className="whitespace-nowrap"
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
                                    {kind !== 'endpoint' && !isDagSchedulesOnly && (
                                        <LemonSelect
                                            className="h-9"
                                            disabledReason={sync || materializationAccessReason}
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
                                (status === 'Running' || status === 'Cancelled') && rows_materialized === 0
                                    ? '~'
                                    : humanFriendlyNumber(rows_materialized),
                        },
                        {
                            title: 'Updated',
                            dataIndex: 'last_run_at',
                            render: (_, { last_run_at }: DataModelingJob) => humanFriendlyDetailedTime(last_run_at),
                        },
                        {
                            title: 'Duration',
                            render: (_, job: DataModelingJob) => {
                                if (job.status === 'Running') {
                                    return 'In progress'
                                }
                                const start = new Date(job.created_at).getTime()
                                const end = new Date(job.last_run_at).getTime()

                                if (start > end) {
                                    return 'N/A'
                                }

                                return humanFriendlyDuration((end - start) / 1000)
                            },
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
