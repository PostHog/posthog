import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { IconFullScreen } from 'lib/lemon-ui/icons'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNode } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailLineage({ id }: { id: string }): JSX.Element {
    const {
        lineageGraph,
        lineageGraphLoading,
        lineageGraphError,
        effectiveLastRunAt,
        effectiveLastRunStatus,
        lineageModalOpen,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { openLineageModal, closeLineageModal, loadLineageGraph } = useActions(nodeDetailSceneLogic({ id }))

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

    const openNode = (node: DataModelingNode): void => {
        router.actions.push(urls.nodeDetail(node.id, 'lineage'))
    }

    if (lineageGraphLoading) {
        return (
            <div className="flex flex-1 min-h-[400px] max-h-[70vh] items-center justify-center border rounded bg-bg-light">
                <Spinner />
            </div>
        )
    }

    if (lineageGraphError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadLineageGraph }}>
                Couldn't load lineage.
            </LemonBanner>
        )
    }

    if (nodes.length <= 1) {
        return <p className="mb-0 text-secondary">No upstream or downstream dependencies found.</p>
    }

    return (
        <>
            <div className="flex-1 min-h-[400px] max-h-[70vh] w-full border rounded bg-bg-light">
                <LineageGraph
                    nodes={nodes}
                    edges={lineageGraph?.edges ?? []}
                    currentNodeId={lineageGraph?.currentNodeId}
                    variant="full"
                    interactive
                    showControls
                    showMinimap
                    onNodeClick={openNode}
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
                            openNode(node)
                        }}
                    />
                </div>
            </LemonModal>
        </>
    )
}
