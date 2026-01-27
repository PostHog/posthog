import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTag, LemonTagType, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { urls } from 'scenes/urls'

import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery, DataWarehouseSavedQueryRunHistory } from '~/types'

import { PAGE_SIZE, viewsTabLogic } from './viewsTabLogic'

const STATUS_TAG_SETTINGS: Record<string, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    Cancelled: 'muted',
    Modified: 'warning',
}

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
    if (loading) {
        return <Spinner className="text-sm" />
    }

    if (!runHistory || runHistory.length === 0) {
        return <span className="text-muted">-</span>
    }

    // Show up to 5 most recent runs, reversed so the most recent is on the right
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
    if (loading || count === undefined) {
        return <Spinner className="text-sm" />
    }
    return <span>{count}</span>
}

export function ViewsTab(): JSX.Element {
    const {
        filteredViews,
        filteredMaterializedViews,
        visibleMaterializedViews,
        visibleViews,
        viewsLoading,
        searchTerm,
        materializedViewDependenciesMapLoading,
        viewDependenciesMapLoading,
        runHistoryMapLoading,
        materializedViewsCurrentPage,
        viewsCurrentPage,
    } = useValues(viewsTabLogic)
    const { setSearchTerm, deleteView, runMaterialization, setMaterializedViewsPage, setViewsPage } =
        useActions(viewsTabLogic)

    return (
        <div className="space-y-4">
            {(filteredViews.length > 0 || filteredMaterializedViews.length > 0 || searchTerm) && (
                <div className="flex gap-2 justify-between items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search views..."
                        onChange={setSearchTerm}
                        value={searchTerm}
                    />
                </div>
            )}

            {/* Materialized Views Section */}
            {filteredMaterializedViews.length > 0 && (
                <div>
                    <h3 className="text-lg font-semibold mb-2">Materialized views</h3>
                    <p className="text-muted mb-2">
                        Materialized views are refreshed on a schedule and stored as tables for faster query
                        performance.
                    </p>
                    <LemonTable
                        dataSource={visibleMaterializedViews}
                        loading={viewsLoading}
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, view: DataWarehouseSavedQuery) =>
                                    view.managed_viewset_kind !== null ? (
                                        <>
                                            <Tooltip
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
                                            to={urls.sqlEditor({ view_id: view.id })}
                                            title={view.name}
                                            description="Materialized view"
                                        />
                                    ),
                            },
                            {
                                title: 'Last run',
                                key: 'last_run_at',
                                render: (_, view) => {
                                    return view.last_run_at ? (
                                        <TZLabel time={view.last_run_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                                    ) : (
                                        'Never'
                                    )
                                },
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                render: (_, view) => {
                                    if (!view.status) {
                                        return null
                                    }
                                    const tagContent = (
                                        <LemonTag type={STATUS_TAG_SETTINGS[view.status] || 'default'}>
                                            {view.status}
                                        </LemonTag>
                                    )
                                    return view.latest_error && view.status === 'Failed' ? (
                                        <Tooltip title={view.latest_error}>{tagContent}</Tooltip>
                                    ) : (
                                        tagContent
                                    )
                                },
                            },
                            {
                                title: 'Run history',
                                key: 'run_history',
                                tooltip: 'Recent run status (up to 5 most recent)',
                                render: (_, view) => (
                                    <RunHistoryDisplay runHistory={view.run_history} loading={runHistoryMapLoading} />
                                ),
                            },
                            {
                                title: 'Upstream',
                                key: 'upstream_count',
                                tooltip: 'Number of immediate upstream dependencies',
                                render: (_, view) => (
                                    <DependencyCount
                                        count={view.upstream_dependency_count}
                                        loading={materializedViewDependenciesMapLoading}
                                    />
                                ),
                            },
                            {
                                title: 'Downstream',
                                key: 'downstream_count',
                                tooltip: 'Number of immediate downstream dependencies',
                                render: (_, view) => (
                                    <DependencyCount
                                        count={view.downstream_dependency_count}
                                        loading={materializedViewDependenciesMapLoading}
                                    />
                                ),
                            },
                            {
                                key: 'actions',
                                width: 0,
                                render: (_, view) => (
                                    <More
                                        overlay={
                                            <>
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
                                                <LemonButton
                                                    status="danger"
                                                    onClick={() => deleteView(view.id)}
                                                    disabledReason={getDisabledReason(view)}
                                                >
                                                    Delete
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                ),
                            },
                        ]}
                        pagination={{
                            controlled: true,
                            pageSize: PAGE_SIZE,
                            currentPage: materializedViewsCurrentPage,
                            entryCount: filteredMaterializedViews.length,
                            onForward: () => {
                                setMaterializedViewsPage(materializedViewsCurrentPage + 1)
                            },
                            onBackward: () => {
                                setMaterializedViewsPage(materializedViewsCurrentPage - 1)
                            },
                        }}
                    />
                </div>
            )}

            {/* Regular Views Section */}
            {filteredViews.length > 0 && (
                <div>
                    <h3 className="text-lg font-semibold mb-2">Views</h3>
                    <p className="text-muted mb-2">
                        Views are virtual tables created from SQL queries. They are computed on-the-fly when queried.
                    </p>
                    <LemonTable
                        dataSource={visibleViews}
                        loading={viewsLoading}
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, view: DataWarehouseSavedQuery) =>
                                    view.managed_viewset_kind !== null ? (
                                        <>
                                            <Tooltip
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
                                    ) : (
                                        <LemonTableLink to={urls.sqlEditor({ view_id: view.id })} title={view.name} />
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
                                title: 'Upstream',
                                key: 'upstream_count',
                                tooltip: 'Number of immediate upstream dependencies',
                                render: (_, view) => (
                                    <DependencyCount
                                        count={view.upstream_dependency_count}
                                        loading={viewDependenciesMapLoading}
                                    />
                                ),
                            },
                            {
                                title: 'Downstream',
                                key: 'downstream_count',
                                tooltip: 'Number of immediate downstream dependencies',
                                render: (_, view) => (
                                    <DependencyCount
                                        count={view.downstream_dependency_count}
                                        loading={viewDependenciesMapLoading}
                                    />
                                ),
                            },
                            {
                                key: 'actions',
                                width: 0,
                                render: (_, view) => (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton
                                                    status="danger"
                                                    onClick={() => deleteView(view.id)}
                                                    disabledReason={getDisabledReason(view)}
                                                >
                                                    Delete
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                ),
                            },
                        ]}
                        pagination={{
                            controlled: true,
                            pageSize: PAGE_SIZE,
                            currentPage: viewsCurrentPage,
                            entryCount: filteredViews.length,
                            onForward: () => {
                                setViewsPage(viewsCurrentPage + 1)
                            },
                            onBackward: () => {
                                setViewsPage(viewsCurrentPage - 1)
                            },
                        }}
                    />
                </div>
            )}

            {/* Empty State */}
            {!viewsLoading && filteredViews.length === 0 && filteredMaterializedViews.length === 0 && (
                <div className="text-center py-12">
                    <h3 className="text-xl font-semibold mb-2">No views found</h3>
                    {searchTerm ? (
                        <p className="text-muted">No views match your search. Try adjusting your search term.</p>
                    ) : (
                        <p className="text-muted">
                            Create your first view to transform and organize your data warehouse tables.
                        </p>
                    )}
                    <LemonButton type="primary" to={urls.sqlEditor()} className="inline-block">
                        Create view
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
