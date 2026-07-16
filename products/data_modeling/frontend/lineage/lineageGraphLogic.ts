import { MarkerType, Position, type Edge as ReactFlowEdge, type Node as ReactFlowNode } from '@xyflow/react'
import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'

import { getFormattedNodes } from 'scenes/data-warehouse/scene/modeling/autolayout'
import { ElkDirection, NodeHandle } from 'scenes/data-warehouse/scene/modeling/types'

import { DataModelingEdge, DataModelingNode } from '~/types'

import type { lineageGraphLogicType } from './lineageGraphLogicType'
import { LineageNodeData, LineageVariant } from './LineageNode'

const NODE_SIZES: Record<LineageVariant, { width: number; height: number }> = {
    full: { width: 200, height: 90 },
    canvas: { width: 180, height: 120 },
}

export interface LineageGraphLayout {
    nodes: ReactFlowNode<LineageNodeData>[]
    edges: ReactFlowEdge[]
}

export interface LineageGraphLogicProps {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
    variant: LineageVariant
    direction: ElkDirection
}

function handlesForDirection(nodeId: string, direction: ElkDirection): NodeHandle[] {
    const isDown = direction === 'DOWN'
    return [
        { id: `target_${nodeId}`, type: 'target', position: isDown ? Position.Top : Position.Left },
        { id: `source_${nodeId}`, type: 'source', position: isDown ? Position.Bottom : Position.Right },
    ]
}

// Layout depends only on the graph's structure — per-node state/callbacks are decorated onto the
// laid-out nodes at render time, so caller-supplied inline callbacks never retrigger the ELK pass.
async function layoutGraph(
    nodes: DataModelingNode[],
    edges: DataModelingEdge[],
    variant: LineageVariant,
    direction: ElkDirection
): Promise<LineageGraphLayout> {
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
            state: {},
            callbacks: {},
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
    return { nodes: laidOut as unknown as ReactFlowNode<LineageNodeData>[], edges: rfEdges }
}

export const lineageGraphLogic = kea<lineageGraphLogicType>([
    path(['products', 'data_modeling', 'frontend', 'lineage', 'lineageGraphLogic']),
    props({} as LineageGraphLogicProps),
    key((props) => `${props.variant}-${props.direction}-${props.nodes.map((n) => n.id).join(',')}`),
    actions({
        computeLayout: true,
        layoutComputed: (layout: LineageGraphLayout) => ({ layout }),
    }),
    reducers({
        layout: [
            null as LineageGraphLayout | null,
            {
                layoutComputed: (_, { layout }) => layout,
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        computeLayout: async (_, breakpoint) => {
            const layout = await layoutGraph(props.nodes, props.edges, props.variant, props.direction)
            breakpoint()
            actions.layoutComputed(layout)
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (
            props.nodes !== oldProps.nodes ||
            props.edges !== oldProps.edges ||
            props.variant !== oldProps.variant ||
            props.direction !== oldProps.direction
        ) {
            actions.computeLayout()
        }
    }),
    afterMount(({ actions }) => {
        actions.computeLayout()
    }),
])
