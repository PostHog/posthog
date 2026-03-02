import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    EdgeTypes,
    MiniMap,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { JourneyFlowEdge, ProfileFlowEdge } from './FunnelFlowEdge'
import { AnyFlowNode, funnelFlowGraphLogic } from './funnelFlowGraphLogic'
import { JourneyFlowNode, ProfileFlowNode } from './FunnelFlowNode'
import { PathFlowEdge } from './PathFlowEdge'
import { PathFlowNode } from './PathFlowNode'

const NODE_TYPES = {
    journey: JourneyFlowNode,
    profile: ProfileFlowNode,
    pathNode: PathFlowNode,
} as NodeTypes

const EDGE_TYPES = {
    journey: JourneyFlowEdge,
    profile: ProfileFlowEdge,
    pathFlow: PathFlowEdge,
} as EdgeTypes

const PROFILE_GRAPH_HEIGHT = 140

function FunnelFlowGraphContent(): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const { fitView: fitViewImperative } = useReactFlow()
    const { isDarkModeOn } = useValues(themeLogic)
    const { insightProps } = useValues(insightLogic)
    const { laidOutNodes, edges, nodeType, fitViewOptions } = useValues(funnelFlowGraphLogic(insightProps))
    const isProfileMode = nodeType === 'profile'

    const onInit = useCallback(
        (instance: ReactFlowInstance<AnyFlowNode>) => {
            instance.fitView(fitViewOptions)
        },
        [fitViewOptions]
    )

    const closeOpenPopovers = useCallback(() => {
        document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    }, [])

    return (
        <div
            ref={containerRef}
            className="relative w-full"
            style={{ height: isProfileMode ? PROFILE_GRAPH_HEIGHT : 'var(--insight-viz-min-height)' }}
        >
            {!isProfileMode && <style>{'.react-flow__edgelabel-renderer { z-index: 5; }'}</style>}
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
