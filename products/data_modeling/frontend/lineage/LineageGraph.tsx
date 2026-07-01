import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    MarkerType,
    MiniMap,
    Panel,
    Position,
    ReactFlow,
    ReactFlowProvider,
    type Edge as ReactFlowEdge,
    type Node as ReactFlowNode,
} from '@xyflow/react'
import { useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { IconArchive } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { getFormattedNodes } from 'scenes/data-warehouse/scene/modeling/autolayout'
import { ElkDirection, NodeHandle } from 'scenes/data-warehouse/scene/modeling/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataModelingEdge, DataModelingNode } from '~/types'

import {
    LINEAGE_NODE_TYPES,
    LineageNodeCallbacks,
    LineageNodeData,
    LineageNodeState,
    LineageVariant,
} from './LineageNode'

export type { LineageVariant, LineageNodeState, LineageNodeCallbacks } from './LineageNode'

const NODE_SIZES: Record<LineageVariant, { width: number; height: number }> = {
    compact: { width: 160, height: 55 },
    full: { width: 200, height: 90 },
    canvas: { width: 180, height: 120 },
}

export interface LineageGraphProps {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
    /** Highlighted "you are here" node, rendered with a target marker + accent border */
    currentNodeId?: string
    variant?: LineageVariant
    direction?: ElkDirection
    /** Enable zoom/pan. Off by default for inline previews */
    interactive?: boolean
    showMinimap?: boolean
    showControls?: boolean
    className?: string
    loading?: boolean
    emptyMessage?: string
    /** Per-node visual state (running, dimmed, highlighted), computed by the caller */
    nodeState?: (node: DataModelingNode) => LineageNodeState
    /** Per-node affordances (click, run, edit), wired by the caller to its own logic */
    nodeCallbacks?: (node: DataModelingNode) => LineageNodeCallbacks
    /** Convenience click handler, used when nodeCallbacks is not provided */
    onNodeClick?: (node: DataModelingNode) => void
    /** Caller-specific chrome (search, legend, layout toggle) rendered over the canvas */
    panels?: ReactNode
}

function handlesForDirection(nodeId: string, direction: ElkDirection): NodeHandle[] {
    const isDown = direction === 'DOWN'
    return [
        { id: `target_${nodeId}`, type: 'target', position: isDown ? Position.Top : Position.Left },
        { id: `source_${nodeId}`, type: 'source', position: isDown ? Position.Bottom : Position.Right },
    ]
}

async function layoutGraph(props: LineageGraphProps): Promise<{ nodes: ReactFlowNode[]; edges: ReactFlowEdge[] }> {
    const {
        nodes,
        edges,
        variant = 'compact',
        direction = 'RIGHT',
        currentNodeId,
        nodeState,
        nodeCallbacks,
        onNodeClick,
    } = props
    const { width, height } = NODE_SIZES[variant]

    const rfNodes: ReactFlowNode<LineageNodeData>[] = nodes.map((node) => ({
        id: node.id,
        type: 'lineage',
        position: { x: 0, y: 0 },
        width,
        height,
        data: {
            node,
            variant,
            direction,
            state: { isCurrent: node.id === currentNodeId, ...nodeState?.(node) },
            callbacks: nodeCallbacks?.(node) ?? { onClick: onNodeClick ? () => onNodeClick(node) : undefined },
            handles: handlesForDirection(node.id, direction),
        },
    }))

    const rfEdges: ReactFlowEdge[] = edges.map((edge) => ({
        id: edge.id,
        source: edge.source_id,
        target: edge.target_id,
        sourceHandle: `source_${edge.source_id}`,
        targetHandle: `target_${edge.target_id}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
    }))

    const laidOut = await getFormattedNodes(rfNodes as any, rfEdges, direction)
    return { nodes: laidOut as unknown as ReactFlowNode[], edges: rfEdges }
}

function LineageGraphContent(props: LineageGraphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const [layout, setLayout] = useState<{ nodes: ReactFlowNode[]; edges: ReactFlowEdge[] } | null>(null)

    useEffect(() => {
        let cancelled = false
        void layoutGraph(props).then((result) => {
            if (!cancelled) {
                setLayout(result)
            }
        })
        return () => {
            cancelled = true
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        props.nodes,
        props.edges,
        props.variant,
        props.direction,
        props.currentNodeId,
        props.nodeState,
        props.nodeCallbacks,
    ])

    if (!layout) {
        return (
            <div className="flex items-center justify-center w-full h-full">
                <Spinner />
            </div>
        )
    }

    return (
        <ReactFlow
            colorMode={isDarkModeOn ? 'dark' : 'light'}
            nodes={layout.nodes}
            edges={layout.edges}
            nodeTypes={LINEAGE_NODE_TYPES}
            nodesDraggable={false}
            nodesConnectable={false}
            fitView
            minZoom={0.1}
            maxZoom={2}
            zoomOnScroll={props.interactive ?? false}
            panOnScroll={props.interactive ?? false}
            zoomOnPinch={props.interactive ?? false}
            zoomOnDoubleClick={props.interactive ?? false}
            proOptions={{ hideAttribution: true }}
        >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            {props.showControls && <Controls showInteractive={false} position="bottom-right" />}
            {props.showMinimap && (
                <MiniMap zoomable pannable position="bottom-left" nodeStrokeWidth={2} className="hidden lg:block" />
            )}
            {props.panels && <Panel position="top-right">{props.panels}</Panel>}
        </ReactFlow>
    )
}

export function LineageGraph(props: LineageGraphProps): JSX.Element {
    if (props.loading) {
        return (
            <div className="flex items-center justify-center w-full h-full">
                <Spinner />
            </div>
        )
    }
    if (props.nodes.length === 0) {
        return (
            <div className="flex flex-col w-full h-full items-center justify-center p-4">
                <IconArchive className="text-5xl mb-2 text-tertiary" />
                <p className="text-sm text-center text-balance text-tertiary">
                    {props.emptyMessage ?? 'No tables or views found'}
                </p>
            </div>
        )
    }
    return (
        <ReactFlowProvider>
            <LineageGraphContent {...props} />
        </ReactFlowProvider>
    )
}
