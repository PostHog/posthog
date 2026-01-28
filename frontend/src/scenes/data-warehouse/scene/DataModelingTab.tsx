import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDirectedGraph, IconList } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonTable, LemonTag, LemonTagType, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { DataModelingNode, DataModelingNodeType } from '~/types'

import { PAGE_SIZE, dataModelingNodesLogic } from './dataModelingNodesLogic'
import { DataModelingEditor } from './modeling/DataModelingEditor'

const NODE_TYPE_TAG_SETTINGS: Record<DataModelingNodeType, { label: string; type: LemonTagType }> = {
    table: { label: 'Table', type: 'default' },
    view: { label: 'View', type: 'primary' },
    matview: { label: 'Materialized view', type: 'success' },
}

function DependencyCount({ count, loading }: { count?: number; loading?: boolean }): JSX.Element {
    if (loading || count === undefined) {
        return <Spinner className="text-sm" />
    }
    return <span>{count}</span>
}

function NodeProperty({ value }: { value: unknown }): JSX.Element {
    if (value === null || value === undefined) {
        return <span className="text-muted">-</span>
    }
    if (typeof value === 'boolean') {
        return (
            <LemonTag type={value ? 'success' : 'default'} size="small">
                {value ? 'Yes' : 'No'}
            </LemonTag>
        )
    }
    if (typeof value === 'object') {
        return <code className="bg-bg-light rounded px-1 py-0.5 text-xs font-mono">{JSON.stringify(value)}</code>
    }
    return <span className="text-default">{String(value)}</span>
}

type ViewMode = 'graph' | 'list'

export function DataModelingTab(): JSX.Element {
    const { viewNodes, visibleNodes, nodesLoading, searchTerm, currentPage } = useValues(dataModelingNodesLogic)
    const { setSearchTerm, setCurrentPage } = useActions(dataModelingNodesLogic)
    const [viewMode, setViewMode] = useState<ViewMode>('graph')

    if (viewMode === 'graph') {
        return (
            <div className="space-y-4 h-full">
                <div className="flex gap-2 justify-between items-center">
                    {(viewNodes.length > 0 || searchTerm) && (
                        <LemonInput
                            type="search"
                            placeholder="Search models..."
                            onChange={setSearchTerm}
                            value={searchTerm}
                        />
                    )}
                    <LemonSegmentedButton
                        value={viewMode}
                        onChange={(value) => setViewMode(value)}
                        options={[
                            { value: 'graph', icon: <IconDirectedGraph />, tooltip: 'Graph view' },
                            { value: 'list', icon: <IconList />, tooltip: 'List view' },
                        ]}
                        size="small"
                    />
                </div>
                <div className="h-[550px] border rounded-lg overflow-hidden">
                    <DataModelingEditor />
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex gap-2 justify-between items-center">
                {(viewNodes.length > 0 || searchTerm) && (
                    <LemonInput
                        type="search"
                        placeholder="Search models..."
                        onChange={setSearchTerm}
                        value={searchTerm}
                    />
                )}
                <LemonSegmentedButton
                    value={viewMode}
                    onChange={(value) => setViewMode(value)}
                    options={[
                        { value: 'graph', icon: <IconDirectedGraph />, tooltip: 'Graph view' },
                        { value: 'list', icon: <IconList />, tooltip: 'List view' },
                    ]}
                    size="small"
                />
            </div>

            {viewNodes.length > 0 && (
                <div>
                    <h3 className="text-lg font-semibold mb-2">Models</h3>
                    <p className="text-muted mb-2">
                        Models represent tables, views, and materialized views in your data modeling DAG.
                    </p>
                    <LemonTable
                        dataSource={visibleNodes}
                        loading={nodesLoading}
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, node: DataModelingNode) => (
                                    <span className="font-bold text-primary">{node.name}</span>
                                ),
                            },
                            {
                                title: 'Type',
                                key: 'type',
                                render: (_, node: DataModelingNode) => {
                                    const settings = NODE_TYPE_TAG_SETTINGS[node.type]
                                    return <LemonTag type={settings.type}>{settings.label}</LemonTag>
                                },
                            },
                            {
                                title: 'DAG',
                                key: 'dag_id',
                                render: (_, node: DataModelingNode) => (
                                    <span className="text-muted">{node.dag_id}</span>
                                ),
                            },
                            {
                                title: 'Upstream',
                                key: 'upstream_count',
                                tooltip: 'Total number of upstream nodes',
                                render: (_, node: DataModelingNode) => (
                                    <DependencyCount count={node.upstream_count} loading={nodesLoading} />
                                ),
                            },
                            {
                                title: 'Downstream',
                                key: 'downstream_count',
                                tooltip: 'Total number of downstream nodes',
                                render: (_, node: DataModelingNode) => (
                                    <DependencyCount count={node.downstream_count} loading={nodesLoading} />
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
                                title: 'Properties',
                                key: 'properties',
                                render: (_, node: DataModelingNode) => {
                                    const props = (node.properties as Record<string, unknown>)?.user as
                                        | Record<string, unknown>
                                        | undefined
                                    if (!props || Object.keys(props).length === 0) {
                                        return <span className="text-muted">-</span>
                                    }
                                    return (
                                        <div className="flex flex-col gap-1">
                                            {Object.entries(props).map(([key, value]) => (
                                                <div key={key} className="text-xs">
                                                    <span className="font-medium">{key}:</span>{' '}
                                                    <NodeProperty value={value} />
                                                </div>
                                            ))}
                                        </div>
                                    )
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
                </div>
            )}

            {!nodesLoading && viewNodes.length === 0 && (
                <div className="text-center py-12">
                    <h3 className="text-xl font-semibold mb-2">No models found</h3>
                    {searchTerm ? (
                        <p className="text-muted">No models match your search. Try adjusting your search term.</p>
                    ) : (
                        <p className="text-muted">Models will appear here when materialized views are created.</p>
                    )}
                </div>
            )}
        </div>
    )
}
