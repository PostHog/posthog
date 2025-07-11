import { IconRevert, IconTarget, IconX } from '@posthog/icons'

import { LemonDialog, LemonTable, Link, Spinner } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDetailedTime, humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataModelingJob, DataWarehouseSyncInterval, LineageNode, OrNever } from '~/types'

import { multitabEditorLogic } from '../multitabEditorLogic'
import { infoTabLogic } from './infoTabLogic'
import { UpstreamGraph } from './graph/UpstreamGraph'

interface QueryInfoProps {
    codeEditorKey: string
}

const OPTIONS = [
    {
        value: 'never' as OrNever,
        label: ' No resync',
    },
    {
        value: '5min' as DataWarehouseSyncInterval,
        label: ' Resync every 5 mins',
    },
    {
        value: '30min' as DataWarehouseSyncInterval,
        label: ' Resync every 30 mins',
    },
    {
        value: '1hour' as DataWarehouseSyncInterval,
        label: ' Resync every 1 hour',
    },
    {
        value: '6hour' as DataWarehouseSyncInterval,
        label: ' Resync every 6 hours',
    },
    {
        value: '12hour' as DataWarehouseSyncInterval,
        label: ' Resync every 12 hours',
    },
    {
        value: '24hour' as DataWarehouseSyncInterval,
        label: ' Resync Daily',
    },
    {
        value: '7day' as DataWarehouseSyncInterval,
        label: ' Resync Weekly',
    },
    {
        value: '30day' as DataWarehouseSyncInterval,
        label: ' Resync Monthly',
    },
]

export function QueryInfo({ codeEditorKey }: QueryInfoProps): JSX.Element {
    const { sourceTableItems } = useValues(infoTabLogic({ codeEditorKey: codeEditorKey }))
    const { editingView, upstream, upstreamViewMode } = useValues(multitabEditorLogic)
    const { runDataWarehouseSavedQuery, saveAsView, setUpstreamViewMode } = useActions(multitabEditorLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isLineageDependencyViewEnabled = featureFlags[FEATURE_FLAGS.LINEAGE_DEPENDENCY_VIEW]

    const {
        dataWarehouseSavedQueryMapById,
        updatingDataWarehouseSavedQuery,
        initialDataWarehouseSavedQueryLoading,
        dataModelingJobs,
        hasMoreJobsToLoad,
    } = useValues(dataWarehouseViewsLogic)
    const {
        updateDataWarehouseSavedQuery,
        loadOlderDataModelingJobs,
        cancelDataWarehouseSavedQuery,
        revertMaterialization,
    } = useActions(dataWarehouseViewsLogic)

    // note: editingView is stale, but dataWarehouseSavedQueryMapById gets updated
    const savedQuery = editingView ? dataWarehouseSavedQueryMapById[editingView.id] : null

    if (initialDataWarehouseSavedQueryLoading) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <Spinner className="text-lg" />
            </div>
        )
    }

    return (
        <div className="overflow-auto" data-attr="sql-editor-sidebar-query-info-pane">
            <div className="flex flex-col flex-1 gap-4">
                <div>
                    <div className="flex flex-row items-center gap-2">
                        <h3 className="mb-0">Materialization</h3>
                        <LemonTag type="warning">BETA</LemonTag>
                        {savedQuery?.latest_error && savedQuery.status === 'Failed' && (
                            <Tooltip title={savedQuery.latest_error}>
                                <LemonTag type="danger">Error</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    <div>
                        {savedQuery?.sync_frequency ? (
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
                                        loading={savedQuery?.status === 'Running'}
                                        disabledReason={
                                            savedQuery?.status === 'Running' && 'Materialization is already running'
                                        }
                                        onClick={() => editingView && runDataWarehouseSavedQuery(editingView.id)}
                                        type="secondary"
                                        sideAction={{
                                            icon: <IconX fontSize={16} />,
                                            tooltip: 'Cancel materialization',
                                            onClick: () => editingView && cancelDataWarehouseSavedQuery(editingView.id),
                                            disabledReason:
                                                savedQuery?.status !== 'Running' && 'Materialization is not running',
                                        }}
                                    >
                                        {savedQuery?.status === 'Running' ? 'Running...' : 'Sync now'}
                                    </LemonButton>
                                    <LemonSelect
                                        className="h-9"
                                        disabledReason={
                                            savedQuery?.status === 'Running'
                                                ? 'Materialization is already running'
                                                : false
                                        }
                                        value={
                                            editingView
                                                ? dataWarehouseSavedQueryMapById[editingView.id]?.sync_frequency ||
                                                  'never'
                                                : 'never'
                                        }
                                        onChange={(newValue) => {
                                            if (editingView && newValue) {
                                                updateDataWarehouseSavedQuery({
                                                    id: editingView.id,
                                                    sync_frequency: newValue,
                                                    types: [[]],
                                                    lifecycle: 'update',
                                                })
                                            }
                                        }}
                                        loading={updatingDataWarehouseSavedQuery}
                                        options={OPTIONS}
                                    />
                                    {editingView && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            tooltip="Revert materialized view to view"
                                            disabledReason={
                                                savedQuery?.status === 'Running' &&
                                                'Cannot revert while materialization is running'
                                            }
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
                                                        onClick: () => revertMaterialization(editingView.id),
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
                                    you to run queries faster and more efficiently. Learn more about materialization{' '}
                                    <Link
                                        data-attr="materializing-help"
                                        to="https://posthog.com/docs/data-warehouse/views#materializing-and-scheduling-a-view"
                                        target="_blank"
                                    >
                                        here
                                    </Link>
                                    .
                                </p>
                                <LemonButton
                                    size="small"
                                    onClick={() => {
                                        if (editingView) {
                                            updateDataWarehouseSavedQuery({
                                                id: editingView.id,
                                                sync_frequency: '24hour',
                                                types: [[]],
                                                lifecycle:
                                                    dataModelingJobs && dataModelingJobs.results.length > 0
                                                        ? 'update'
                                                        : 'create',
                                            })
                                        } else {
                                            saveAsView({ materializeAfterSave: true })
                                        }
                                    }}
                                    type="primary"
                                    loading={updatingDataWarehouseSavedQuery}
                                >
                                    {editingView ? 'Materialize' : 'Save and materialize'}
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
                {savedQuery && (
                    <>
                        <div>
                            <h3>Materialization Runs</h3>
                            <p className="text-xs">
                                The last runs for this materialized view. These can be scheduled or run on demand.
                            </p>
                        </div>
                        <LemonTable
                            size="small"
                            loading={initialDataWarehouseSavedQueryLoading}
                            dataSource={dataModelingJobs?.results || []}
                            columns={[
                                {
                                    title: 'Status',
                                    dataIndex: 'status',
                                    render: (_, { status, error }: DataModelingJob) => {
                                        const statusToType: Record<string, LemonTagType> = {
                                            Completed: 'success',
                                            Failed: 'danger',
                                            Running: 'warning',
                                        }
                                        const type = statusToType[status] || 'warning'

                                        return error ? (
                                            <Tooltip title={error}>
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
                                    render: (_, { last_run_at }: DataModelingJob) =>
                                        humanFriendlyDetailedTime(last_run_at),
                                },
                                {
                                    title: 'Duration',
                                    render: (_, job: DataModelingJob) => {
                                        if (job.status === 'Running') {
                                            return 'In progress'
                                        }
                                        // Convert date strings to timestamps before subtraction
                                        const start = new Date(job.created_at).getTime()
                                        const end = new Date(job.last_run_at).getTime()

                                        if (start > end) {
                                            return 'N/A'
                                        }

                                        return humanFriendlyDuration((end - start) / 1000)
                                    },
                                },
                            ]}
                            nouns={['run', 'runs']}
                            emptyState="No runs available"
                            footer={
                                hasMoreJobsToLoad && (
                                    <div className="flex items-center m-2">
                                        <LemonButton
                                            center
                                            fullWidth
                                            onClick={() => loadOlderDataModelingJobs()}
                                            loading={initialDataWarehouseSavedQueryLoading}
                                        >
                                            Load older runs
                                        </LemonButton>
                                    </div>
                                )
                            }
                        />
                    </>
                )}
                {!isLineageDependencyViewEnabled && (
                    <>
                        <div>
                            <h3>Dependencies</h3>
                            <p className="text-xs">Dependencies are tables that this query uses.</p>
                        </div>
                        <LemonTable
                            size="small"
                            columns={[
                                {
                                    key: 'Name',
                                    title: 'Name',
                                    render: (_, { name }) => name,
                                },
                                {
                                    key: 'Type',
                                    title: 'Type',
                                    render: (_, { type }) => type,
                                },
                                {
                                    key: 'Status',
                                    title: 'Status',
                                    render: (_, { type, status, last_run_at }) => {
                                        if (type === 'source') {
                                            return (
                                                <Tooltip title="This is a source table, so it doesn't have a status">
                                                    <span className="text-secondary">N/A</span>
                                                </Tooltip>
                                            )
                                        }
                                        if (last_run_at === 'never' && !status) {
                                            return (
                                                <Tooltip title="This is a view, so it's always available with the latest data">
                                                    <span className="text-secondary">Available</span>
                                                </Tooltip>
                                            )
                                        }
                                        return status
                                    },
                                },
                                {
                                    key: 'Last run at',
                                    title: 'Last run at',
                                    render: (_, { type, last_run_at, status }) => {
                                        if (type === 'source') {
                                            return (
                                                <Tooltip title="This is a source table, so it is never run">
                                                    <span className="text-secondary">N/A</span>
                                                </Tooltip>
                                            )
                                        }
                                        if (last_run_at === 'never' && !status) {
                                            return (
                                                <Tooltip title="This is a view, so it is never run">
                                                    <span className="text-secondary">N/A</span>
                                                </Tooltip>
                                            )
                                        }
                                        return humanFriendlyDetailedTime(last_run_at)
                                    },
                                },
                            ]}
                            dataSource={sourceTableItems}
                        />
                    </>
                )}

                {upstream && editingView && upstream.nodes.length > 0 && isLineageDependencyViewEnabled && (
                    <>
                        <div>
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="mb-1">Tables we use</h3>
                                    <p className="text-xs mb-0">Tables and views that this query relies on.</p>
                                </div>
                                <LemonSegmentedButton
                                    value={upstreamViewMode}
                                    onChange={(mode) => setUpstreamViewMode(mode)}
                                    options={[
                                        {
                                            value: 'table',
                                            label: 'Table',
                                        },
                                        {
                                            value: 'graph',
                                            label: 'Graph',
                                        },
                                    ]}
                                    size="small"
                                />
                            </div>
                        </div>
                        {upstreamViewMode === 'table' ? (
                            <LemonTable
                                size="small"
                                columns={[
                                    {
                                        key: 'name',
                                        title: 'Name',
                                        render: (_, { name }) => (
                                            <div className="flex items-center gap-1">
                                                {name === editingView?.name && (
                                                    <Tooltip
                                                        placement="right"
                                                        title="This is the currently viewed query"
                                                    >
                                                        <IconTarget className="text-warning" />
                                                    </Tooltip>
                                                )}
                                                {name}
                                            </div>
                                        ),
                                    },
                                    {
                                        key: 'type',
                                        title: 'Type',
                                        render: (_, { type, last_run_at }) => {
                                            if (type === 'view') {
                                                return last_run_at ? 'Mat. View' : 'View'
                                            }
                                            return 'Table'
                                        },
                                    },
                                    {
                                        key: 'upstream',
                                        title: 'Direct Upstream',
                                        render: (_, node) => {
                                            const upstreamNodes = upstream.edges
                                                .filter((edge) => edge.target === node.id)
                                                .map((edge) => upstream.nodes.find((n) => n.id === edge.source))
                                                .filter((n): n is LineageNode => n !== undefined)

                                            if (upstreamNodes.length === 0) {
                                                return <span className="text-secondary">None</span>
                                            }

                                            return (
                                                <div className="flex flex-wrap gap-1">
                                                    {upstreamNodes.map((upstreamNode) => (
                                                        <LemonTag key={upstreamNode.id} type="primary">
                                                            {upstreamNode.name}
                                                        </LemonTag>
                                                    ))}
                                                </div>
                                            )
                                        },
                                    },
                                    {
                                        key: 'last_run_at',
                                        title: 'Last Run At',
                                        render: (_, { last_run_at, sync_frequency }) => {
                                            if (!last_run_at) {
                                                return 'On demand'
                                            }
                                            const numericSyncFrequency = Number(sync_frequency)
                                            const frequencyMap: Record<string, string> = {
                                                300: '5 mins',
                                                1800: '30 mins',
                                                3600: '1 hour',
                                                21600: '6 hours',
                                                43200: '12 hours',
                                                86400: '24 hours',
                                                604800: '1 week',
                                            }

                                            return `${humanFriendlyDetailedTime(last_run_at)} ${
                                                frequencyMap[numericSyncFrequency]
                                                    ? `every ${frequencyMap[numericSyncFrequency]}`
                                                    : ''
                                            }`
                                        },
                                    },
                                ]}
                                dataSource={upstream.nodes}
                            />
                        ) : (
                            <div className="h-96 border border-border rounded-lg overflow-hidden">
                                <UpstreamGraph codeEditorKey={codeEditorKey} />
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
