import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { LemonTable, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNode } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'

import { NODE_TYPE_TAG_SETTINGS, STATUS_TAG_SETTINGS } from '../nodeDetailConstants'
import type { LineageRow } from '../nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailLineage({ id }: { id: string }): JSX.Element | null {
    const {
        filteredLineage,
        lineageGraph,
        lineageGraphLoading,
        lineageFilter,
        lineageRows,
        effectiveLastRunAt,
        effectiveLastRunStatus,
        lineageModalOpen,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { setLineageFilter, openLineageModal, closeLineageModal } = useActions(nodeDetailSceneLogic({ id }))

    // The current node's freshest status/run come from its materialization jobs, not the graph payload
    const nodes = useMemo((): DataModelingNode[] => {
        if (!filteredLineage) {
            return []
        }
        return filteredLineage.nodes.map((node) =>
            node.id === filteredLineage.currentNodeId
                ? {
                      ...node,
                      last_run_at: effectiveLastRunAt ?? node.last_run_at,
                      last_run_status: (effectiveLastRunStatus as DataModelingJobStatus) ?? node.last_run_status,
                  }
                : node
        )
    }, [filteredLineage, effectiveLastRunAt, effectiveLastRunStatus])

    if (lineageGraphLoading) {
        return (
            <div className="flex items-center justify-center h-72 border rounded bg-bg-light mt-4">
                <Spinner />
            </div>
        )
    }

    if ((lineageGraph?.nodes.length ?? 0) <= 1) {
        return <div className="text-muted text-sm mt-4">No upstream or downstream dependencies found.</div>
    }

    return (
        <div className="flex flex-col gap-2 mt-4">
            <div>
                <LemonSegmentedButton
                    size="small"
                    value={lineageFilter}
                    onChange={(value) => setLineageFilter(value)}
                    options={[
                        { value: 'all' as const, label: 'All' },
                        { value: 'upstream' as const, label: 'Upstream' },
                        { value: 'downstream' as const, label: 'Downstream' },
                    ]}
                />
            </div>
            <div className="h-[420px] w-full border rounded bg-bg-light">
                <LineageGraph
                    nodes={nodes}
                    edges={filteredLineage?.edges ?? []}
                    currentNodeId={filteredLineage?.currentNodeId}
                    variant="full"
                    interactive
                    showControls
                    showMinimap
                    onNodeClick={(node) => router.actions.push(urls.nodeDetail(node.id))}
                    onToggleFullscreen={openLineageModal}
                />
            </div>
            <LemonTable
                size="small"
                dataSource={lineageRows}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, { node }: LineageRow) => (
                            <Link to={urls.nodeDetail(node.id)} className="font-semibold">
                                {node.name}
                            </Link>
                        ),
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, { node }: LineageRow) => {
                            const tag = NODE_TYPE_TAG_SETTINGS[node.type]
                            return tag ? <LemonTag type={tag.type}>{tag.label}</LemonTag> : null
                        },
                    },
                    {
                        title: 'Direction',
                        key: 'direction',
                        render: (_, { direction }: LineageRow) =>
                            direction === 'upstream' ? 'Upstream' : 'Downstream',
                    },
                    {
                        title: 'Last run',
                        key: 'last_run',
                        render: (_, { node }: LineageRow) =>
                            node.last_run_at ? (
                                <div className="flex items-center gap-2">
                                    {node.last_run_status && (
                                        <LemonTag type={STATUS_TAG_SETTINGS[node.last_run_status] ?? 'default'}>
                                            {node.last_run_status}
                                        </LemonTag>
                                    )}
                                    <TZLabel time={node.last_run_at} />
                                </div>
                            ) : null,
                    },
                ]}
                nouns={['dependency', 'dependencies']}
                emptyState="No dependencies in this direction"
            />
            <LemonModal
                isOpen={lineageModalOpen}
                onClose={closeLineageModal}
                title="Lineage"
                width="calc(100vw - 4rem)"
                maxWidth="calc(100vw - 4rem)"
            >
                <div className="h-[calc(100vh-12rem)]">
                    <LineageGraph
                        nodes={nodes}
                        edges={filteredLineage?.edges ?? []}
                        currentNodeId={filteredLineage?.currentNodeId}
                        variant="full"
                        interactive
                        showControls
                        onNodeClick={(node) => {
                            closeLineageModal()
                            router.actions.push(urls.nodeDetail(node.id))
                        }}
                    />
                </div>
            </LemonModal>
        </div>
    )
}
