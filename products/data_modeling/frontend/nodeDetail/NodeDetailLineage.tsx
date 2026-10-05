import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconExpand45, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNode } from '~/types'

import { LineageGraph } from '../lineage/LineageGraph'
import { lineageNodeUrl } from '../lineage/lineageNodeUrl'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

function nodeLineageUrl(node: DataModelingNode): string {
    return lineageNodeUrl(node, 'lineage')
}

export function NodeDetailLineage({ id }: { id: string }): JSX.Element {
    const nodesDraggable = useFeatureFlag('DATA_MODELING_LINEAGE_NODE_DRAGGING')
    const {
        lineageGraph,
        lineageGraphLoading,
        lineageGraphError,
        effectiveLastRunAt,
        effectiveLastRunStatus,
        lineageModalOpen,
        lineageNodePositions,
        node,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { openLineageModal, closeLineageModal, loadLineageGraph, lineageNodeDragStopped, resetLineageNodePositions } =
        useActions(nodeDetailSceneLogic({ id }))

    // The current node's freshest status/run come from its materialization jobs, not the graph payload
    const nodes = useMemo((): DataModelingNode[] => {
        if (!lineageGraph) {
            return []
        }
        return lineageGraph.nodes.map((node) =>
            node.id === lineageGraph.currentNodeId
                ? {
                      ...node,
                      last_run_at: effectiveLastRunAt ?? node.last_run_at,
                      last_run_status: (effectiveLastRunStatus as DataModelingJobStatus) ?? node.last_run_status,
                  }
                : node
        )
    }, [lineageGraph, effectiveLastRunAt, effectiveLastRunStatus])
    const focusNodeIds = useMemo(
        () => (lineageGraph?.currentNodeId ? new Set([lineageGraph.currentNodeId]) : null),
        [lineageGraph?.currentNodeId]
    )

    const openNode = (node: DataModelingNode): void => {
        router.actions.push(nodeLineageUrl(node))
    }

    if (!lineageGraphLoading && lineageGraphError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadLineageGraph }}>
                Couldn't load lineage.
            </LemonBanner>
        )
    }

    if (!lineageGraphLoading && nodes.length <= 1 && !nodes[0]?.lineage_issue) {
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
        <>
            <div className="flex-1 min-h-[400px] max-h-[70vh] w-full border rounded bg-bg-light overflow-hidden">
                <LineageGraph
                    nodes={nodes}
                    edges={lineageGraph?.edges ?? []}
                    currentNodeId={lineageGraph?.currentNodeId}
                    focusNodeIds={focusNodeIds}
                    loading={lineageGraphLoading}
                    loadingCenter={lineageGraphLoading && node ? { name: node.name, type: node.type } : undefined}
                    variant="full"
                    interactive
                    nodesDraggable={nodesDraggable}
                    nodePositions={nodesDraggable ? lineageNodePositions : undefined}
                    nodeOpenUrl={nodesDraggable ? nodeLineageUrl : undefined}
                    onNodeDragStop={
                        nodesDraggable ? (node, position) => lineageNodeDragStopped(node.id, position) : undefined
                    }
                    onResetNodePositions={nodesDraggable ? resetLineageNodePositions : undefined}
                    showControls
                    showMinimap
                    onNodeClick={nodesDraggable ? undefined : openNode}
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
                        edges={lineageGraph?.edges ?? []}
                        currentNodeId={lineageGraph?.currentNodeId}
                        focusNodeIds={focusNodeIds}
                        variant="full"
                        interactive
                        nodesDraggable={nodesDraggable}
                        nodePositions={nodesDraggable ? lineageNodePositions : undefined}
                        nodeOpenUrl={nodesDraggable ? nodeLineageUrl : undefined}
                        onNodeDragStop={
                            nodesDraggable ? (node, position) => lineageNodeDragStopped(node.id, position) : undefined
                        }
                        onResetNodePositions={nodesDraggable ? resetLineageNodePositions : undefined}
                        showControls
                        onNodeClick={
                            nodesDraggable
                                ? undefined
                                : (node) => {
                                      closeLineageModal()
                                      openNode(node)
                                  }
                        }
                    />
                </div>
            </LemonModal>
        </>
    )
}
