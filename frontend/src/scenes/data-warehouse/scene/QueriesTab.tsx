import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { DataWarehouseSavedQuery } from '~/types'

import { queriesTabLogic } from './queriesTabLogic'

const STATUS_TAG_SETTINGS: Record<string, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    Cancelled: 'muted',
    Modified: 'warning',
}

export function QueriesTab(): JSX.Element {
    const { filteredViews, filteredMaterializedViews, viewsLoading, searchTerm } = useValues(queriesTabLogic)
    const { setSearchTerm, deleteView, runMaterialization } = useActions(queriesTabLogic)

    return (
        <div className="space-y-4">
            <div className="flex gap-2 justify-between items-center">
                <LemonInput
                    type="search"
                    placeholder="Search views..."
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
            </div>

            {/* Materialized Views Section */}
            {filteredMaterializedViews.length > 0 && (
                <div>
                    <h3 className="text-lg font-semibold mb-2">Materialized views</h3>
                    <p className="text-muted mb-2">
                        Materialized views are refreshed on a schedule and stored as tables for faster query
                        performance.
                    </p>
                    <LemonTable
                        dataSource={filteredMaterializedViews}
                        loading={viewsLoading}
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, view: DataWarehouseSavedQuery) => (
                                    <LemonTableLink
                                        to={urls.sqlEditor(undefined, view.id)}
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
                                        <TZLabel
                                            time={view.last_run_at}
                                            formatDate="MMM DD, YYYY"
                                            formatTime="HH:mm"
                                        />
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
                                title: 'Upstream',
                                key: 'upstream_count',
                                tooltip: 'Number of immediate upstream dependencies',
                                render: (_, view) => view.upstream_dependency_count ?? 0,
                            },
                            {
                                title: 'Downstream',
                                key: 'downstream_count',
                                tooltip: 'Number of immediate downstream dependencies',
                                render: (_, view) => view.downstream_dependency_count ?? 0,
                            },
                            {
                                key: 'actions',
                                width: 0,
                                render: (_, view) => (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton onClick={() => runMaterialization(view.id)}>
                                                    Run now
                                                </LemonButton>
                                                <LemonButton status="danger" onClick={() => deleteView(view.id)}>
                                                    Delete
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                ),
                            },
                        ]}
                        pagination={{ pageSize: 10 }}
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
                        dataSource={filteredViews}
                        loading={viewsLoading}
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, view: DataWarehouseSavedQuery) => (
                                    <LemonTableLink
                                        to={urls.sqlEditor(undefined, view.id)}
                                        title={view.name}
                                        description="View"
                                    />
                                ),
                            },
                            {
                                title: 'Created',
                                key: 'created_at',
                                render: (_, view) =>
                                    view.created_at ? (
                                        <TZLabel
                                            time={view.created_at}
                                            formatDate="MMM DD, YYYY"
                                            formatTime="HH:mm"
                                        />
                                    ) : (
                                        '-'
                                    ),
                            },
                            {
                                title: 'Upstream',
                                key: 'upstream_count',
                                tooltip: 'Number of immediate upstream dependencies',
                                render: (_, view) => view.upstream_dependency_count ?? 0,
                            },
                            {
                                title: 'Downstream',
                                key: 'downstream_count',
                                tooltip: 'Number of immediate downstream dependencies',
                                render: (_, view) => view.downstream_dependency_count ?? 0,
                            },
                            {
                                key: 'actions',
                                width: 0,
                                render: (_, view) => (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton status="danger" onClick={() => deleteView(view.id)}>
                                                    Delete
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                ),
                            },
                        ]}
                        pagination={{ pageSize: 10 }}
                    />
                </div>
            )}

            {/* Empty State */}
            {!viewsLoading && filteredViews.length === 0 && filteredMaterializedViews.length === 0 && (
                <div className="text-center py-12">
                    <h3 className="text-xl font-semibold mb-2">No views found</h3>
                    {searchTerm ? (
                        <p className="text-muted">
                            No views match your search. Try adjusting your search term.
                        </p>
                    ) : (
                        <p className="text-muted">
                            Create your first view to transform and organize your data warehouse tables.
                        </p>
                    )}
                    <LemonButton type="primary" to={urls.sqlEditor()} className="mt-4">
                        Create view
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
