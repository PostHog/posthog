import { useActions, useValues } from 'kea'

import { IconExpand45, IconExternal } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { QuillCheckCallout } from 'products/data_quality/frontend/QuillCheckCallout'

import { LineageGraph } from '../lineage/LineageGraph'
import { LINEAGE_FIT_VIEW_OPTIONS, nodeLineageUrl } from './NodeDetailLineage'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { QuillNodeDetailLineageTypeFilter } from './QuillNodeDetailLineageTypeFilter'

export function QuillNodeDetailLineage({ id }: { id: string }): JSX.Element {
    const {
        lineageGraph,
        lineageGraphLoading,
        lineageGraphError,
        lineageNodes: nodes,
        lineageHiddenNodeBridging,
        lineageModalOpen,
        lineageNodePositions,
        node,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { openLineageModal, closeLineageModal, loadLineageGraph, lineageNodeDragStopped, resetLineageNodePositions } =
        useActions(nodeDetailSceneLogic({ id }))
    const fullLineageUrl = urls.dataCatalog('lineage')
    const edges = lineageHiddenNodeBridging?.edges ?? []

    if (!lineageGraphLoading && lineageGraphError) {
        return (
            <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: loadLineageGraph }}>
                Couldn't load lineage.
            </QuillCheckCallout>
        )
    }

    if (!lineageGraphLoading && (lineageGraph?.nodes.length ?? 0) <= 1 && !nodes[0]?.lineage_issue) {
        return (
            <Empty className="min-h-64 rounded-lg border border-border">
                <EmptyHeader>
                    <EmptyTitle>No connected models</EmptyTitle>
                    <EmptyDescription>
                        Lineage shows the sources this model reads from and the models that use it. This model has no
                        recorded connections yet.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" render={<LinkPrimitive to={fullLineageUrl} />}>
                        <IconExternal />
                        Explore all lineage
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <QuillNodeDetailLineageTypeFilter id={id} />
            <div className="h-[calc(100vh-20rem)] min-h-100 w-full overflow-hidden rounded-lg border border-border">
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
                    onNodeDragStop={(lineageNode, position) => lineageNodeDragStopped(lineageNode.id, position)}
                    onResetNodePositions={resetLineageNodePositions}
                    showControls
                    showMinimap
                    panels={
                        <div className="flex flex-col gap-1">
                            <Button
                                variant="outline"
                                size="icon"
                                render={<LinkPrimitive to={fullLineageUrl} />}
                                tooltip="Open the full graph"
                                aria-label="Open the full graph"
                            >
                                <IconExternal />
                            </Button>
                            <Button
                                variant="outline"
                                size="icon"
                                onClick={openLineageModal}
                                tooltip="Full screen"
                                aria-label="Full screen"
                            >
                                <IconExpand45 />
                            </Button>
                        </div>
                    }
                />
            </div>
            <Dialog open={lineageModalOpen} onOpenChange={(open: boolean) => !open && closeLineageModal()}>
                <DialogContent size="full">
                    <DialogHeader>
                        <DialogTitle>Lineage</DialogTitle>
                    </DialogHeader>
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
                            onNodeDragStop={(lineageNode, position) => lineageNodeDragStopped(lineageNode.id, position)}
                            onResetNodePositions={resetLineageNodePositions}
                            showControls
                        />
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    )
}
