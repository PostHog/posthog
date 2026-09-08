import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import { AccessControlObjectModal } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObjectModal'
import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryRunHistory,
} from '~/types'

import { STATUS_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'

import { TableCertificationTag } from '../TableCertificationBadge'
import { PAGE_SIZE, ViewTypeFilter, viewsTabLogic } from './viewsTabLogic'

type ViewColumn = LemonTableColumn<DataWarehouseSavedQuery, keyof DataWarehouseSavedQuery | undefined>

const TYPE_FILTER_OPTIONS: { value: ViewTypeFilter; label: string }[] = [
    { value: 'all', label: 'All types' },
    { value: 'materialized', label: 'Materialized' },
    { value: 'view', label: 'Views' },
]

const getDisabledReason = (view: DataWarehouseSavedQuery): string | undefined => {
    if (view.managed_viewset_kind !== null) {
        return `Cannot delete a view that belongs to a managed viewset. You can turn the viewset off in the ${urls.dataWarehouseManagedViewsets()} page.`
    }
    if (view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT) {
        return `Cannot delete a view that belongs to an endpoint. You can disable materialization on this endpoint's page.`
    }
    return undefined
}

function RunHistoryDisplay({
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
        return <span className="text-muted">-</span>
    }

    const displayRuns = runHistory.slice(0, 5).reverse()

    return (
        <div className="flex gap-1">
            {displayRuns.map((run, index) => {
                const friendlyTime = run.timestamp ? humanFriendlyDetailedTime(run.timestamp) : ''
                return (
                    <Tooltip
                        key={index}
                        title={`${run.status}${friendlyTime ? ` - ${friendlyTime}` : ''}`}
                        placement="top"
                    >
                        <div
                            className={`w-4 h-4 rounded-sm ${run.status === 'Completed' ? 'bg-success' : 'bg-danger'}`}
                        />
                    </Tooltip>
                )
            })}
        </div>
    )
}

function DependencyCount({ count, loading }: { count?: number; loading?: boolean }): JSX.Element {
    if (count === undefined) {
        return loading ? <Spinner className="text-sm" /> : <span className="text-muted">-</span>
    }
    return <span>{count}</span>
}

function StatusCell({ view }: { view: DataWarehouseSavedQuery }): JSX.Element {
    if (!view.is_materialized) {
        return <span className="text-muted">-</span>
    }
    const suspension = Object.values(view.suspended ?? {})[0]
    if (suspension) {
        return (
            <Tooltip title={suspension.reason} interactive>
                <LemonTag type="warning">Suspended</LemonTag>
            </Tooltip>
        )
    }
    if (!view.status) {
        return <span className="text-muted">-</span>
    }
    if (view.latest_error && view.status === 'Failed') {
        return (
            <Tooltip title={view.latest_error} interactive>
                <LemonTag type="danger">Failed</LemonTag>
            </Tooltip>
        )
    }
    return <LemonTag type={STATUS_TAG_SETTINGS[view.status] || 'default'}>{view.status}</LemonTag>
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
        typeFilter,
        currentPage,
        dependenciesMapLoading,
        runHistoryMapLoading,
        accessControlModalOpen,
        editingAccessControlView,
        featureFlags,
        viewsMapById,
    } = useValues(viewsTabLogic)
    const {
        setSearchTerm,
        setTypeFilter,
        setPage,
        deleteView,
        runMaterialization,
        openAccessControlModal,
        closeAccessControlModal,
    } = useActions(viewsTabLogic)

    const warehouseAccessControlEnabled = !!featureFlags[FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL]

    const viewLink = (view: DataWarehouseSavedQuery): { to: string; description?: string } => {
        if (view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT) {
            return { to: urls.endpoint(view.name), description: `Created by the ${view.name} endpoint` }
        }
        if (view.managed_viewset_kind !== null) {
            return {
                to: getViewUrl?.(view) ?? urls.dataWarehouseManagedViewsets(),
                description: `Managed by the ${view.managed_viewset_kind} viewset`,
            }
        }
        return { to: getViewUrl?.(view) ?? urls.sqlEditor({ view_id: view.id }) }
    }

    const columns: LemonTableColumns<DataWarehouseSavedQuery> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, view) => {
                const { to, description } = viewLink(view)
                return (
                    <div className="flex items-center gap-2">
                        <LemonTableLink to={to} title={view.name} description={description} />
                        <TableCertificationTag certification={viewsMapById[view.id]?.certification} />
                    </div>
                )
            },
        } as ViewColumn,
        {
            title: 'Type',
            key: 'is_materialized',
            tooltip:
                'A materialized view is refreshed on a schedule and stored as a table. A view runs its query each time it is read.',
            render: (_, view) =>
                view.is_materialized ? (
                    <LemonTag type="highlight">Materialized</LemonTag>
                ) : (
                    <LemonTag type="default">View</LemonTag>
                ),
        } as ViewColumn,
        {
            title: 'Status',
            key: 'status',
            render: (_, view) => <StatusCell view={view} />,
        } as ViewColumn,
        {
            title: 'Last run',
            key: 'last_run_at',
            render: (_, view) => {
                if (!view.is_materialized) {
                    return <span className="text-muted">-</span>
                }
                return view.last_run_at ? (
                    <TZLabel time={view.last_run_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                ) : (
                    'Never'
                )
            },
        } as ViewColumn,
        {
            title: 'Run history',
            key: 'run_history',
            tooltip: 'Up to 5 most recent runs, oldest first',
            render: (_, view) =>
                view.is_materialized ? (
                    <RunHistoryDisplay runHistory={view.run_history} loading={runHistoryMapLoading} />
                ) : (
                    <span className="text-muted">-</span>
                ),
        } as ViewColumn,
        {
            title: 'Upstream',
            key: 'upstream_dependency_count',
            tooltip: 'Number of immediate upstream dependencies',
            render: (_, view) => (
                <DependencyCount count={view.upstream_dependency_count} loading={dependenciesMapLoading} />
            ),
        } as ViewColumn,
        {
            title: 'Downstream',
            key: 'downstream_dependency_count',
            tooltip: 'Number of immediate downstream dependencies',
            render: (_, view) => (
                <DependencyCount count={view.downstream_dependency_count} loading={dependenciesMapLoading} />
            ),
        } as ViewColumn,
        createdAtColumn<DataWarehouseSavedQuery>() as ViewColumn,
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
                                            view.status === 'Running' ? 'Materialization is already running' : undefined
                                        }
                                    >
                                        Sync now
                                    </LemonButton>
                                </AccessControlAction>
                            )}
                            {warehouseAccessControlEnabled && view.managed_viewset_kind === null && (
                                <LemonButton onClick={() => openAccessControlModal(view)}>Access control</LemonButton>
                            )}
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
        } as ViewColumn,
    ]

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
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    placeholder="Search views..."
                    onChange={setSearchTerm}
                    value={searchTerm}
                    data-attr="views-search"
                />
                <LemonSelect
                    value={typeFilter}
                    onChange={setTypeFilter}
                    options={TYPE_FILTER_OPTIONS}
                    size="small"
                    data-attr="views-type-filter"
                />
            </div>
            <LemonTable
                dataSource={visibleViews}
                loading={viewsLoading}
                columns={columns}
                rowKey="id"
                emptyState={
                    searchTerm || typeFilter !== 'all' ? (
                        'No views match your filters.'
                    ) : (
                        <div className="flex flex-col items-start gap-2">
                            <span>Create your first view to transform and organize your data warehouse tables.</span>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton type="primary" size="small" to={urls.sqlEditor({ source: 'view' })}>
                                    Create view
                                </LemonButton>
                            </AccessControlAction>
                        </div>
                    )
                }
                pagination={{
                    controlled: true,
                    pageSize: PAGE_SIZE,
                    currentPage,
                    entryCount: filteredViews.length,
                    onForward: () => setPage(currentPage + 1),
                    onBackward: () => setPage(currentPage - 1),
                }}
            />
        </div>
    )
}
