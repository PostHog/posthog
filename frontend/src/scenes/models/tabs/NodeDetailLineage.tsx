import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { IconFullScreen } from 'lib/lemon-ui/icons'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNode } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailLineage({ id }: { id: string }): JSX.Element | null {
    const { lineageGraph, lineageGraphLoading, effectiveLastRunAt, effectiveLastRunStatus, lineageModalOpen } =
        useValues(nodeDetailSceneLogic({ id }))
    const { openLineageModal, closeLineageModal } = useActions(nodeDetailSceneLogic({ id }))

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

    if (lineageGraphLoading) {
        return (
            <div className="space-y-2 mt-4">
                <h3 className="text-lg font-semibold">Lineage</h3>
                <div className="flex items-center justify-center h-72 border rounded bg-bg-light">
                    <Spinner />
                </div>
            </div>
        )
    }

    if (nodes.length <= 1) {
        return (
            <div className="space-y-2 mt-4">
                <h3 className="text-lg font-semibold">Lineage</h3>
                <div className="text-muted text-sm">No upstream or downstream dependencies found.</div>
            </div>
        )
    }

    return (
        <div className="space-y-2 mt-4">
            <h3 className="text-lg font-semibold">Lineage</h3>
            <div className="h-[500px] w-full border rounded bg-bg-light">
                <LineageGraph
                    nodes={nodes}
                    edges={lineageGraph?.edges ?? []}
                    currentNodeId={lineageGraph?.currentNodeId}
                    variant="full"
                    interactive
                    showControls
                    showMinimap
                    onNodeClick={(node) => router.actions.push(urls.nodeDetail(node.id))}
                    panels={
                        <div className="flex flex-col gap-1">
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.dataOps('modeling')}
                                tooltip="Open full DAG view"
                                icon={<IconExternal />}
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={openLineageModal}
                                tooltip="Fullscreen"
                                icon={<IconFullScreen />}
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
