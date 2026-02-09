import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonTable,
    LemonTag,
    LemonTagType,
    Spinner,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { DataModelingNode, DataModelingNodeType } from '~/types'

import { dataModelingLogic } from '../dataModelingLogic'
import { PAGE_SIZE } from './constants'

const NODE_TYPE_TAG_SETTINGS: Record<DataModelingNodeType, { label: string; type: LemonTagType }> = {
    table: { label: 'Table', type: 'default' },
    view: { label: 'View', type: 'primary' },
    matview: { label: 'Materialized view', type: 'success' },
}

function NodeDependencyCount({ count, loading }: { count?: number; loading?: boolean }): JSX.Element {
    if (loading || count === undefined) {
        return <Spinner className="text-sm" />
    }
    return <span>{count}</span>
}

export function TableView(): JSX.Element {
    const {
        viewNodes,
        visibleNodes,
        nodesLoading,
        currentPage,
        debouncedSearchTerm,
        availableDagIds,
        availableTypes,
        filterDagIds,
        filterTypes,
    } = useValues(dataModelingLogic)
    const { setCurrentPage, toggleFilterDagId, clearFilterDagIds, toggleFilterType, clearFilterTypes } =
        useActions(dataModelingLogic)

    if (!nodesLoading && viewNodes.length === 0) {
        return (
            <div className="text-center py-12">
                <h3 className="text-xl font-semibold mb-2">No models found</h3>
                {debouncedSearchTerm ? (
                    <p className="text-muted">No models match your search. Try adjusting your search term.</p>
                ) : (
                    <p className="text-muted">Models will appear here when views or materialized views are created.</p>
                )}
            </div>
        )
    }
    return (
        <LemonTable
            className="max-h-[calc(100vh-17rem)] overflow-y-auto"
            stickyHeader={true}
            dataSource={visibleNodes}
            loading={nodesLoading}
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    render: (_, node: DataModelingNode) => <span className="font-bold text-primary">{node.name}</span>,
                },
                {
                    title: 'Type',
                    key: 'type',
                    render: (_, node: DataModelingNode) => {
                        const settings = NODE_TYPE_TAG_SETTINGS[node.type]
                        return <LemonTag type={settings.type}>{settings.label}</LemonTag>
                    },
                    moreIcon: <IconFilter />,
                    moreFilterCount: filterTypes.length,
                    more: (
                        <div className="space-y-1">
                            <div className="px-2 py-1 space-y-1">
                                {availableTypes.map((type: DataModelingNodeType) => (
                                    <LemonCheckbox
                                        key={type}
                                        label={NODE_TYPE_TAG_SETTINGS[type].label}
                                        checked={filterTypes.includes(type)}
                                        onChange={() => toggleFilterType(type)}
                                        size="small"
                                        fullWidth
                                    />
                                ))}
                                {availableTypes.length === 0 && <span className="text-muted text-xs">No types</span>}
                            </div>
                            <LemonDivider className="my-1" />
                            <LemonButton size="small" fullWidth onClick={clearFilterTypes}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ),
                },
                {
                    title: 'DAG',
                    key: 'dag_id',
                    render: (_, node: DataModelingNode) => <span className="text-muted">{node.dag_id}</span>,
                    moreIcon: <IconFilter />,
                    moreFilterCount: filterDagIds.length,
                    more: (
                        <div className="space-y-1">
                            <div className="px-2 py-1 space-y-1 max-h-60 overflow-y-auto">
                                {availableDagIds.map((dagId: string) => (
                                    <LemonCheckbox
                                        key={dagId}
                                        label={dagId}
                                        checked={filterDagIds.includes(dagId)}
                                        onChange={() => toggleFilterDagId(dagId)}
                                        size="small"
                                        fullWidth
                                    />
                                ))}
                                {availableDagIds.length === 0 && <span className="text-muted text-xs">No DAGs</span>}
                            </div>
                            <LemonDivider className="my-1" />
                            <LemonButton size="small" fullWidth onClick={clearFilterDagIds}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ),
                },
                {
                    title: 'Upstream',
                    key: 'upstream_count',
                    tooltip: 'Total number of upstream nodes',
                    render: (_, node: DataModelingNode) => (
                        <NodeDependencyCount count={node.upstream_count} loading={nodesLoading} />
                    ),
                },
                {
                    title: 'Downstream',
                    key: 'downstream_count',
                    tooltip: 'Total number of downstream nodes',
                    render: (_, node: DataModelingNode) => (
                        <NodeDependencyCount count={node.downstream_count} loading={nodesLoading} />
                    ),
                },
                {
                    title: 'Created',
                    key: 'created_at',
                    render: (_, node: DataModelingNode) =>
                        node.created_at ? (
                            <TZLabel time={node.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                        ) : (
                            '-'
                        ),
                },
                {
                    title: 'Last run',
                    key: 'last_run_at',
                    render: (_, node: DataModelingNode) => {
                        return node.last_run_at ? <TZLabel time={node.last_run_at} /> : '-'
                    },
                },
                {
                    title: 'Tag',
                    key: 'tag',
                    render: (_, node: DataModelingNode) => {
                        return <span className="font-semibold italic">#{node.user_tag}</span>
                    },
                },
            ]}
            pagination={{
                controlled: true,
                pageSize: PAGE_SIZE,
                currentPage: currentPage,
                entryCount: viewNodes.length,
                onForward: () => {
                    setCurrentPage(currentPage + 1)
                },
                onBackward: () => {
                    setCurrentPage(currentPage - 1)
                },
            }}
        />
    )
}
