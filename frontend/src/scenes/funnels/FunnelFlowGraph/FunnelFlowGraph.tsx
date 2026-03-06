import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    EdgeTypes,
    MiniMap,
    Node,
    NodeTypes,
    ReactFlow,
    ReactFlowInstance,
    ReactFlowProvider,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { isInsightVizNode } from '~/queries/utils'

import { JourneyFlowEdge, ProfileFlowEdge } from './FunnelFlowEdge'
import { funnelFlowGraphLogic, FunnelFlowNodeData } from './funnelFlowGraphLogic'
import { JourneyFlowNode, ProfileFlowNode } from './FunnelFlowNode'

const NODE_TYPES = {
    journey: JourneyFlowNode,
    profile: ProfileFlowNode,
} as NodeTypes

const EDGE_TYPES = {
    journey: JourneyFlowEdge,
    profile: ProfileFlowEdge,
} as EdgeTypes

const PROFILE_GRAPH_HEIGHT = 140

function FunnelFlowGraphContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { insightProps } = useValues(insightLogic)
    // Property filters are only set when in person/group profile, so we can use that as a proxy
    const isProfileMode =
        isInsightVizNode(insightProps.query) &&
        Array.isArray(insightProps.query.source?.properties) &&
        insightProps.query.source.properties.length > 0
    const { laidOutNodes, edges, fitViewOptions } = useValues(funnelFlowGraphLogic({ ...insightProps, isProfileMode }))

    const onInit = useCallback(
        (instance: ReactFlowInstance<Node<FunnelFlowNodeData>>) => {
            instance.fitView(fitViewOptions)
        },
        [fitViewOptions]
    )

    const closeOpenPopovers = useCallback(() => {
        document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    }, [])

    return (
        <div
            className="relative w-full"
            style={{ height: isProfileMode ? PROFILE_GRAPH_HEIGHT : 'var(--insight-viz-min-height)' }}
        >
            <ReactFlow
                nodes={laidOutNodes}
                edges={edges}
                nodeTypes={NODE_TYPES}
                edgeTypes={EDGE_TYPES}
                nodesDraggable={false}
                nodesConnectable={false}
                fitView
                fitViewOptions={fitViewOptions}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                proOptions={{ hideAttribution: true }}
                elevateNodesOnSelect={false}
                minZoom={0.25}
                maxZoom={1.5}
                onInit={onInit}
                onPaneClick={closeOpenPopovers}
                onNodeClick={closeOpenPopovers}
            >
                {!isProfileMode && (
                    <>
                        <Background gap={36} variant={BackgroundVariant.Dots} />
                        <Controls showInteractive={false} fitViewOptions={fitViewOptions} />
                        {laidOutNodes.length > 4 && (
                            <MiniMap
                                zoomable
                                pannable
                                nodeStrokeWidth={3}
                                nodeColor="var(--border)"
                                nodeStrokeColor="var(--border)"
                            />
                        )}
                    </>
                )}
            </ReactFlow>
        </div>
    )
}

export function FunnelFlowGraph(): JSX.Element {
    return (
        <ReactFlowProvider>
            <FunnelFlowGraphContent />
        </ReactFlowProvider>
    )
}
