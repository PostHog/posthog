import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    EdgeTypes,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
} from '@xyflow/react'
import { useValues } from 'kea'
import { useCallback } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { FunnelFlowEdge } from './FunnelFlowEdge'
import { FunnelFlowNode } from './FunnelFlowNode'
import { funnelFlowGraphLogic } from './funnelFlowGraphLogic'

const NODE_TYPES = {
    mandatory: FunnelFlowNode,
    optional: FunnelFlowNode,
} as NodeTypes

const EDGE_TYPES = {
    funnelFlow: FunnelFlowEdge,
} as EdgeTypes

const FIT_VIEW_OPTIONS = {
    padding: 0.2,
    maxZoom: 1,
}

function FunnelFlowGraphContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { insightProps } = useValues(insightLogic)
    const { layoutedNodes, edges } = useValues(funnelFlowGraphLogic(insightProps))

    const closeOpenPopovers = useCallback(() => {
        document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    }, [])

    return (
        <div className="relative w-full" style={{ height: 'var(--insight-viz-min-height)' }}>
            <ReactFlow
                nodes={layoutedNodes}
                edges={edges}
                nodeTypes={NODE_TYPES}
                edgeTypes={EDGE_TYPES}
                nodesDraggable={false}
                nodesConnectable={false}
                fitView
                fitViewOptions={FIT_VIEW_OPTIONS}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                proOptions={{ hideAttribution: true }}
                elevateNodesOnSelect={false}
                minZoom={0.25}
                maxZoom={1.5}
                onPaneClick={closeOpenPopovers}
                onNodeClick={closeOpenPopovers}
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />
                <Controls showInteractive={false} fitViewOptions={FIT_VIEW_OPTIONS} />
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
