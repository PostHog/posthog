import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, MiniMap, Panel, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconArchive } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { ElkDirection } from 'scenes/data-warehouse/scene/modeling/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { lineageGraphLogic } from './lineageGraphLogic'
import { LINEAGE_NODE_TYPES, LineageNodeCallbacks, LineageNodeState, LineageVariant } from './LineageNode'

export type { LineageVariant, LineageNodeState, LineageNodeCallbacks } from './LineageNode'

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

function LineageGraphContent(props: LineageGraphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { currentNodeId, nodeState, nodeCallbacks, onNodeClick } = props
    const { layout } = useValues(
        lineageGraphLogic({
            nodes: props.nodes,
            edges: props.edges,
            variant: props.variant ?? 'full',
            direction: props.direction ?? 'RIGHT',
        })
    )

    if (!layout) {
        return (
            <div className="flex items-center justify-center w-full h-full">
                <Spinner />
            </div>
        )
    }

    // Cheap per-render pass: current-node highlight, state, and callbacks change without relayout
    const decoratedNodes = layout.nodes.map((rfNode) => {
        const node = rfNode.data.node as DataModelingNode
        return {
            ...rfNode,
            data: {
                ...rfNode.data,
                state: { isCurrent: node.id === currentNodeId, ...nodeState?.(node) },
                callbacks: nodeCallbacks?.(node) ?? {
                    onClick: onNodeClick ? () => onNodeClick(node) : undefined,
                },
            },
        }
    })

    return (
        <ReactFlow
            colorMode={isDarkModeOn ? 'dark' : 'light'}
            nodes={decoratedNodes}
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
