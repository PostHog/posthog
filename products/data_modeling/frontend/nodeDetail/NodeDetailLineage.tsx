import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExpand45, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNode } from '~/types'

import { LineageGraph } from '../lineage/LineageGraph'
import { LineageGraphNode, nodesWithHubs } from '../lineage/lineageHiddenNodes'
import { lineageNodeUrl } from '../lineage/lineageNodeUrl'
import { LineageTypeFilter } from '../lineage/LineageTypeFilter'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

function nodeLineageUrl(node: DataModelingNode): string {
    return lineageNodeUrl(node, 'lineage')
}

// Without a cap, a two-node graph scales up to fill the panel and the cards look oversized
const LINEAGE_FIT_VIEW_OPTIONS = { maxZoom: 1 }

export function NodeDetailLineage({ id }: { id: string }): JSX.Element {
    const {
        lineageGraph,
        lineageGraphLoading,
        lineageGraphError,
        effectiveLastRunAt,
        effectiveLastRunStatus,
        lineageModalOpen,
        lineageNodePositions,
        lineageTypeFilter,
        lineageVisibleNodeIds,
        lineageHiddenNodeBridging,
        node,
    } = useValues(nodeDetailSceneLogic({ id }))
    const {
        openLineageModal,
        closeLineageModal,
        loadLineageGraph,
        lineageNodeDragStopped,
        resetLineageNodePositions,
        setLineageTypeFilter,
    } = useActions(nodeDetailSceneLogic({ id }))

    // The current node's freshest status/run come from its materialization jobs, not the graph payload
    const nodes = useMemo((): LineageGraphNode[] => {
        if (!lineageGraph) {
            return []
        }
        const hubNodeIds = lineageHiddenNodeBridging?.hubNodeIds ?? new Set<string>()
        return nodesWithHubs(lineageGraph.nodes, lineageVisibleNodeIds, hubNodeIds).map((node) =>
            node.id === lineageGraph.currentNodeId
                ? {
                      ...node,
                      last_run_at: effectiveLastRunAt ?? node.last_run_at,
                      last_run_status: (effectiveLastRunStatus as DataModelingJobStatus) ?? node.last_run_status,
                  }
                : node
        )
    }, [lineageGraph, lineageVisibleNodeIds, lineageHiddenNodeBridging, effectiveLastRunAt, effectiveLastRunStatus])
    const edges = lineageHiddenNodeBridging?.edges ?? []

    if (!lineageGraphLoading && lineageGraphError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadLineageGraph }}>
                Couldn't load lineage.
            </LemonBanner>
        )
    }

    if (!lineageGraphLoading && (lineageGraph?.nodes.length ?? 0) <= 1 && !nodes[0]?.lineage_issue) {
        return (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded border bg-bg-light p-6 text-center">
                <div className="max-w-120">
                    <h3 className="mb-2">No connected models</h3>
                    <p className="mb-0 text-secondary">
                        Lineage shows the sources this model reads from and the models that use it. This model has no
                        recorded connections yet.
                    </p>
                </div>
                <LemonButton type="secondary" size="small" to={urls.models('lineage')} icon={<IconExternal />}>
                    Explore all lineage
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-start gap-2">
            <LineageTypeFilter
                value={lineageTypeFilter}
                onChange={setLineageTypeFilter}
                dataAttr="node-detail-lineage-type-filter"
            />
            <div className="h-[calc(100vh-20rem)] min-h-[400px] w-full border rounded bg-bg-light overflow-hidden">
                <LineageGraph
                    nodes={nodes}
                    edges={edges}
                    currentNodeId={lineageGraph?.currentNodeId}
                    loading={lineageGraphLoading}
                    loadingCenter={lineageGraphLoading && node ? { name: node.name, type: node.type } : undefined}
                    variant="full"
                    interactive
                    fitViewOptions={LINEAGE_FIT_VIEW_OPTIONS}
                    nodesDraggable
                    nodePositions={lineageNodePositions}
                    nodeOpenUrl={nodeLineageUrl}
                    onNodeDragStop={(node, position) => lineageNodeDragStopped(node.id, position)}
                    onResetNodePositions={resetLineageNodePositions}
                    showControls
                    showMinimap
                    panels={
                        <div className="flex flex-col gap-1">
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.models('lineage')}
                                tooltip="Open the full graph"
                                icon={<IconExternal />}
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={openLineageModal}
                                tooltip="Full screen"
                                icon={<IconExpand45 />}
                            />
                        </div>
                    }
                />
            </div>
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
                        edges={edges}
                        currentNodeId={lineageGraph?.currentNodeId}
                        variant="full"
                        interactive
                        nodesDraggable
                        nodePositions={lineageNodePositions}
                        nodeOpenUrl={nodeLineageUrl}
                        onNodeDragStop={(node, position) => lineageNodeDragStopped(node.id, position)}
                        onResetNodePositions={resetLineageNodePositions}
                        showControls
                    />
                </div>
            </LemonModal>
        </div>
    )
}
