import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconEndpoints, IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
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

import { NodeSuspensionApi } from 'products/data_modeling/frontend/generated/api.schemas'
import { statusBackgroundClass } from 'products/data_modeling/frontend/lineage/nodeStyles'
import { SEARCH_SYNTAX_HELP } from 'products/data_modeling/frontend/lineage/SearchSyntaxHelp'
import { StatusTag } from 'products/data_modeling/frontend/lineage/StatusTag'
import { ModelListRow } from 'products/data_modeling/frontend/modelList'

import { TableCertificationTag } from '../TableCertificationBadge'
import { PAGE_SIZE, ViewTypeFilter, viewsTabLogic } from './viewsTabLogic'

type ViewColumn = LemonTableColumn<ModelListRow, keyof ModelListRow | undefined>

const VIEW_TYPE_TOOLTIPS = {
    materialized: 'Refreshed on a schedule and stored as a table, so a read hits stored rows.',
    view: 'Runs its query every time it is read.',
}

const TYPE_FILTER_OPTIONS: { value: ViewTypeFilter; label: string }[] = [
    { value: 'all', label: 'All types' },
    { value: 'materialized', label: 'Materialized' },
    { value: 'view', label: 'Views' },
    { value: 'endpoint', label: 'Endpoints' },
]

const getDisabledReason = (view: DataWarehouseSavedQuery): string | undefined => {
    if (view.managed_viewset_kind !== null) {
        return `Cannot delete a view that belongs to a managed viewset. You can turn the viewset off in the ${urls.dataWarehouseManagedViewsets()} page.`
    }
    if (view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT) {
        return `Cannot delete a view that belongs to an endpoint. Manage this model on the endpoint's page.`
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
                        <div className={`w-4 h-4 rounded-sm ${statusBackgroundClass(run.status)}`} />
                    </Tooltip>
                )
            })}
        </div>
    )
}

function StatusCell({
    view,
    suspension,
}: {
    view: DataWarehouseSavedQuery
    suspension?: NodeSuspensionApi
}): JSX.Element {
    if (!view.is_materialized) {
        return <span className="text-muted">-</span>
    }
    if (suspension) {
        return (
            <Tooltip
                title={
                    <div className="flex flex-col gap-1">
                        <div>Scheduled runs stopped after this model failed repeatedly.</div>
                        <div className="opacity-75">{suspension.reason}</div>
                    </div>
                }
                interactive
            >
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
    return <StatusTag status={view.status} />
}

interface ViewsTabProps {
    /** Optional function to build the URL when clicking on a view. Defaults to SQL editor. */
    getViewUrl?: (view: DataWarehouseSavedQuery) => string
    /** Saved query id -> suspension. List responses carry no suspension, so the scene passes it in. */
    suspensionByViewId?: Record<string, NodeSuspensionApi | undefined>
}

export function ViewsTab({ getViewUrl, suspensionByViewId }: ViewsTabProps = {}): JSX.Element {
    const {
        filteredViews,
        visibleModelRows,
        visibleViews,
        sorting,
        expandedEndpointNames,
        viewsLoading,
        endpointsError,
        modelEndpointVersions,
        modelEndpointVersionsLoading,
        searchTerm,
        typeFilter,
        currentPage,
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
        setSorting,
        deleteView,
        runMaterialization,
        openAccessControlModal,
        closeAccessControlModal,
        loadModelEndpoints,
        toggleEndpointExpanded,
    } = useActions(viewsTabLogic)

    const paginationState = usePagination(visibleViews, {
        controlled: true,
        pageSize: PAGE_SIZE,
        currentPage,
        entryCount: filteredViews.length,
        onForward: () => setPage(currentPage + 1),
        onBackward: () => setPage(currentPage - 1),
    })

    const warehouseAccessControlEnabled = !!featureFlags[FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL]

    const viewLink = (view: ModelListRow): { to: string; description?: string } => {
        if (view.endpoint) {
            return {
                to: urls.endpoint(view.endpoint.name, view.endpoint.version),
                description: view.endpointVersions
                    ? `${view.endpointVersionCount ?? view.endpointVersions.length} ${(view.endpointVersionCount ?? view.endpointVersions.length) === 1 ? 'version' : 'versions'}`
                    : undefined,
            }
        }
        if (view.managed_viewset_kind !== null) {
            return {
                to: getViewUrl?.(view) ?? urls.dataWarehouseManagedViewsets(),
                description: `Managed by the ${view.managed_viewset_kind} viewset`,
            }
        }
        return { to: getViewUrl?.(view) ?? urls.sqlEditor({ view_id: view.id }) }
    }

    const columns: LemonTableColumns<ModelListRow> = [
        {
            key: 'expand',
            width: 0,
            render: (_, view) =>
                view.endpointVersions && view.endpoint ? (
                    <LemonButton
                        size="xsmall"
                        icon={
                            expandedEndpointNames.includes(view.endpoint.name) ? (
                                <IconChevronDown />
                            ) : (
                                <IconChevronRight />
                            )
                        }
                        data-attr="models-toggle-endpoint-versions"
                        aria-label={`${expandedEndpointNames.includes(view.endpoint.name) ? 'Collapse' : 'Expand'} ${view.endpoint.name}`}
                        onClick={() => toggleEndpointExpanded(view.endpoint!.name)}
                        loading={
                            expandedEndpointNames.includes(view.endpoint.name) &&
                            modelEndpointVersionsLoading &&
                            !modelEndpointVersions[view.endpoint.name]
                        }
                    />
                ) : null,
        },
        {
            title: 'Name',
            key: 'name',
            render: (_, view) => {
                const { to, description } = viewLink(view)
                return (
                    <LemonTableLink
                        className={view.endpoint && !view.endpointVersions ? 'pl-6' : undefined}
                        to={to}
                        title={
                            <span className="flex flex-wrap items-center gap-1 min-w-0">
                                {view.endpointVersions && (
                                    <Tooltip title="Endpoint">
                                        <IconEndpoints className="shrink-0" />
                                    </Tooltip>
                                )}
                                <span className="truncate">
                                    {view.endpoint
                                        ? view.endpointVersions
                                            ? view.endpoint.name
                                            : `v${view.endpoint.version}`
                                        : view.name}
                                </span>

                                {view.endpoint?.is_current && !view.endpointVersions && (
                                    <LemonTag type="primary" size="small">
                                        Current
                                    </LemonTag>
                                )}
                                {view.is_materialized && (
                                    <Tooltip title={VIEW_TYPE_TOOLTIPS.materialized}>
                                        <LemonTag type="highlight" size="small">
                                            Materialized
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                <TableCertificationTag certification={viewsMapById[view.id]?.certification} />
                            </span>
                        }
                        description={view.modelUnavailableReason ?? description}
                        truncateTitle
                        truncateDescription
                    />
                )
            },
        } as ViewColumn,
        {
            title: 'Status',
            key: 'status',
            render: (_, view) =>
                view.modelUnavailableReason ? (
                    <Tooltip title={view.modelUnavailableReason}>
                        <LemonTag type="warning">Model unavailable</LemonTag>
                    </Tooltip>
                ) : (
                    <StatusCell view={view} suspension={suspensionByViewId?.[view.id]} />
                ),
        } as ViewColumn,
        {
            title: 'Last run',
            key: 'last_run_at',
            className: '@max-[48rem]/main-content:hidden',
            render: (_, view) => {
                if (!view.is_materialized || view.isEndpointPlaceholder) {
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
            className: '@max-[64rem]/main-content:hidden',
            tooltip: 'Up to 5 most recent runs, oldest first',
            render: (_, view) =>
                view.is_materialized && !view.isEndpointPlaceholder ? (
                    <RunHistoryDisplay runHistory={view.run_history} loading={runHistoryMapLoading} />
                ) : (
                    <span className="text-muted">-</span>
                ),
        } as ViewColumn,
        {
            ...createdByColumn<ModelListRow>(),
            sorter: true,
            className: '@max-[64rem]/main-content:hidden',
        } as ViewColumn,
        {
            ...createdAtColumn<ModelListRow>(),
            sorter: true,
            className: '@max-[64rem]/main-content:hidden',
        } as ViewColumn,
        {
            key: 'actions',
            width: 0,
            render: (_, view) =>
                view.endpoint ? null : (
                    <More
                        overlay={
                            <>
                                {view.is_materialized && (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.WarehouseObjects}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        <LemonButton
                                            fullWidth
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
                                {warehouseAccessControlEnabled && view.managed_viewset_kind === null && (
                                    <LemonButton fullWidth onClick={() => openAccessControlModal(view)}>
                                        Access control
                                    </LemonButton>
                                )}
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.WarehouseObjects}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={view.user_access_level}
                                >
                                    <LemonButton
                                        fullWidth
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
            {endpointsError && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadModelEndpoints }}>
                    Could not load endpoints. Retry to see all your models.
                </LemonBanner>
            )}
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
                    size="small"
                    placeholder="Search, or +name for upstream"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="w-72"
                    data-attr="views-search"
                />
                <Tooltip title={SEARCH_SYNTAX_HELP}>
                    <IconInfo className="text-base text-secondary" />
                </Tooltip>
                <LemonSelect
                    value={typeFilter}
                    onChange={setTypeFilter}
                    options={TYPE_FILTER_OPTIONS}
                    size="small"
                    data-attr="views-type-filter"
                />
            </div>
            <LemonTable
                footer={<PaginationControl {...paginationState} nouns={['model', 'models']} />}
                dataSource={visibleModelRows}
                sorting={sorting}
                useURLForSorting={false}
                onSort={setSorting}
                loading={viewsLoading}
                columns={columns}
                rowKey={(view) => `${view.endpointVersions ? 'parent' : 'version'}-${view.id}`}
                emptyState={
                    searchTerm || typeFilter !== 'all' ? (
                        'No models match your filters.'
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
            />
        </div>
    )
}
