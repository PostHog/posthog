import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { STATUS_TAG_SETTINGS } from 'scenes/models/nodeDetailConstants'
import { urls } from 'scenes/urls'

import { AccessControlObjectModal } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObjectModal'
import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryRunHistory,
} from '~/types'

import { TableCertificationTag } from '../TableCertificationBadge'
import { PAGE_SIZE, viewsTabLogic } from './viewsTabLogic'

const RUN_HISTORY_SPARKLINE_RUNS = 10

const getDisabledReason = (view: DataWarehouseSavedQuery): string | undefined => {
    if (view.managed_viewset_kind !== null) {
        return `Cannot delete a view that belongs to a managed viewset. You can turn the viewset off in the ${urls.dataWarehouseManagedViewsets()} page.`
    }
    if (view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT) {
        return `Cannot delete a view that belongs to an endpoint. You can disable materialization on this endpoint's page.`
    }

    return undefined
}

function RunHistorySparkline({
    runHistory,
    loading,
}: {
    runHistory?: DataWarehouseSavedQueryRunHistory[]
    loading?: boolean
}): JSX.Element {
    if (loading && !runHistory) {
        return <Spinner className="text-sm" />
    }

    if (!runHistory || runHistory.length === 0) {
        return <span className="text-secondary">-</span>
    }

    // Newest run on the right, like a time series
    const runs = runHistory.slice(0, RUN_HISTORY_SPARKLINE_RUNS).reverse()
    const data: SparklineTimeSeries[] = [
        {
            name: 'Success',
            color: 'success',
            values: runs.map((run) => (run.status === 'Completed' ? 1 : 0)),
        },
        {
            name: 'Running',
            color: 'warning',
            values: runs.map((run) => (run.status === 'Running' ? 1 : 0)),
        },
        {
            name: 'Failed',
            color: 'danger',
            values: runs.map((run) => (run.status === 'Completed' || run.status === 'Running' ? 0 : 1)),
        },
    ]

    return (
        <Sparkline
            data={data}
            labels={runs.map((run) => (run.timestamp ? humanFriendlyDetailedTime(run.timestamp) : ''))}
            className="h-8 w-24"
            maximumIndicator={false}
        />
    )
}

interface ViewsTabProps {
    /** Optional function to build the URL when clicking on a view. Defaults to SQL editor. */
    getViewUrl?: (view: DataWarehouseSavedQuery) => string
}

export function ViewsTab({ getViewUrl }: ViewsTabProps = {}): JSX.Element {
    const {
        filteredViews,
        visibleViews,
        viewsLoading,
        searchTerm,
        runHistoryMapLoading,
        currentPage,
        accessControlModalOpen,
        editingAccessControlView,
        featureFlags,
        viewsMapById,
    } = useValues(viewsTabLogic)
    const { setSearchTerm, deleteView, runMaterialization, setPage, openAccessControlModal, closeAccessControlModal } =
        useActions(viewsTabLogic)

    const warehouseAccessControlEnabled = !!featureFlags[FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL]

    const nameWithCertification = (view: DataWarehouseSavedQuery, content: JSX.Element): JSX.Element => (
        <div className="flex items-center gap-2">
            <div>{content}</div>
            <TableCertificationTag certification={viewsMapById[view.id]?.certification} />
        </div>
    )

    const accessControlMenuButton = (view: DataWarehouseSavedQuery): JSX.Element | null => {
        if (!warehouseAccessControlEnabled || view.managed_viewset_kind !== null) {
            return null
        }
        return <LemonButton onClick={() => openAccessControlModal(view)}>Access control</LemonButton>
    }

    return (
        <div className="space-y-4">
            {editingAccessControlView ? (
                <AccessControlObjectModal
                    isOpen={accessControlModalOpen}
                    onClose={closeAccessControlModal}
                    resource={AccessControlResourceType.WarehouseView}
                    resource_id={editingAccessControlView.id}
                    title={editingAccessControlView.name}
                    description="Control who can query this view. Users without access won't see it and queries referencing it will fail for them."
                />
            ) : null}
            {(filteredViews.length > 0 || searchTerm) && (
                <div className="flex gap-2 justify-between items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search views..."
                        onChange={setSearchTerm}
                        value={searchTerm}
                    />
                </div>
            )}

            {filteredViews.length > 0 && (
                <LemonTable
                    dataSource={visibleViews}
                    loading={viewsLoading}
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, view: DataWarehouseSavedQuery) =>
                                nameWithCertification(
                                    view,
                                    view.managed_viewset_kind !== null ? (
                                        <>
                                            <Tooltip
                                                interactive
                                                title={
                                                    <>
                                                        You cannot edit the definition for a view that belongs to a
                                                        managed viewset. You can enable/disable the viewset in the{' '}
                                                        <Link to={urls.dataWarehouseManagedViewsets()}>
                                                            Managed Viewsets
                                                        </Link>{' '}
                                                        page.
                                                    </>
                                                }
                                            >
                                                <span className="font-bold text-primary">{view.name}</span>
                                            </Tooltip>
                                            <br />
                                            <span className="text-muted text-xs">
                                                Created by the{' '}
                                                <Link to={urls.dataWarehouseManagedViewsets()} className="text-muted">
                                                    <code>{view.managed_viewset_kind}</code>
                                                </Link>{' '}
                                                managed viewset
                                            </span>
                                        </>
                                    ) : view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT ? (
                                        <LemonTableLink
                                            to={urls.endpoint(view.name)}
                                            title={view.name}
                                            description={`Created by the ${view.name} endpoint.`}
                                        />
                                    ) : (
                                        <LemonTableLink
                                            to={getViewUrl?.(view) ?? urls.sqlEditor({ view_id: view.id })}
                                            title={view.name}
                                        />
                                    )
                                ),
                        },
                        {
                            title: 'Materialized',
                            key: 'materialized',
                            render: (_, view) =>
                                view.is_materialized ? (
                                    <LemonTag type="success">Materialized</LemonTag>
                                ) : (
                                    <LemonTag type="default">View</LemonTag>
                                ),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, view) => {
                                if (!view.is_materialized || !view.status) {
                                    return <span className="text-secondary">-</span>
                                }
                                if (view.latest_error && view.status === 'Failed') {
                                    return (
                                        <Tooltip title={view.latest_error} interactive>
                                            <LemonTag type="danger">Failed</LemonTag>
                                        </Tooltip>
                                    )
                                }
                                return (
                                    <LemonTag type={STATUS_TAG_SETTINGS[view.status] || 'default'}>
                                        {view.status}
                                    </LemonTag>
                                )
                            },
                        },
                        {
                            title: 'Last run',
                            key: 'last_run_at',
                            render: (_, view) => {
                                if (!view.is_materialized) {
                                    return <span className="text-secondary">-</span>
                                }
                                return view.last_run_at ? (
                                    <TZLabel time={view.last_run_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                                ) : (
                                    'Never'
                                )
                            },
                        },
                        {
                            title: 'Run history',
                            key: 'run_history',
                            tooltip: 'Recent runs, newest on the right',
                            render: (_, view) =>
                                view.is_materialized ? (
                                    <RunHistorySparkline runHistory={view.run_history} loading={runHistoryMapLoading} />
                                ) : (
                                    <span className="text-secondary">-</span>
                                ),
                        },
                        {
                            title: 'Created',
                            key: 'created_at',
                            render: (_, view) =>
                                view.created_at ? (
                                    <TZLabel time={view.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                                ) : (
                                    '-'
                                ),
                        },
                        {
                            key: 'actions',
                            width: 0,
                            render: (_, view) => (
                                <More
                                    overlay={
                                        <>
                                            {view.is_materialized && (
                                                <AccessControlAction
                                                    resourceType={AccessControlResourceType.WarehouseObjects}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                >
                                                    <LemonButton
                                                        onClick={() => runMaterialization(view.id)}
                                                        disabledReason={
                                                            view.status === 'Running'
                                                                ? 'Materialization is already running'
                                                                : undefined
                                                        }
                                                    >
                                                        Sync now
                                                    </LemonButton>
                                                </AccessControlAction>
                                            )}
                                            {accessControlMenuButton(view)}
                                            <AccessControlAction
                                                resourceType={AccessControlResourceType.WarehouseObjects}
                                                minAccessLevel={AccessControlLevel.Editor}
                                                userAccessLevel={view.user_access_level}
                                            >
                                                <LemonButton
                                                    status="danger"
                                                    onClick={() => deleteView(view.id)}
                                                    disabledReason={getDisabledReason(view)}
                                                >
                                                    Delete
                                                </LemonButton>
                                            </AccessControlAction>
                                        </>
                                    }
                                />
                            ),
                        },
                    ]}
                    pagination={{
                        controlled: true,
                        pageSize: PAGE_SIZE,
                        currentPage,
                        entryCount: filteredViews.length,
                        onForward: () => {
                            setPage(currentPage + 1)
                        },
                        onBackward: () => {
                            setPage(currentPage - 1)
                        },
                    }}
                />
            )}

            {!viewsLoading && filteredViews.length === 0 && (
                <div className="text-center py-12">
                    <h3 className="text-xl font-semibold mb-2">No views found</h3>
                    {searchTerm ? (
                        <p className="text-muted">No views match your search. Try adjusting your search term.</p>
                    ) : (
                        <p className="text-muted">
                            Create your first view to transform and organize your data warehouse tables.
                        </p>
                    )}
                    <AccessControlAction
                        resourceType={AccessControlResourceType.WarehouseObjects}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton type="primary" to={urls.sqlEditor({ source: 'view' })} className="inline-block">
                            Create view
                        </LemonButton>
                    </AccessControlAction>
                </div>
            )}
        </div>
    )
}
