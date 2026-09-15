import { Edge, Position, Node as ReactFlowNode } from '@xyflow/react'
import type { ElkExtendedEdge, ElkNode } from 'elkjs'

import { getElk } from 'lib/elk'

export type ElkDirection = 'DOWN' | 'RIGHT'

export interface NodeHandle {
    id?: string
    type: 'source' | 'target'
    position: Position
    x?: number
    y?: number
}

// Above this node count, ELK's NETWORK_SIMPLEX node placement (which scales
// super-linearly and runs on the main thread) becomes the dominant cost of
// showing the graph. We switch to the much cheaper BRANDES_KOEPF placement for
// large graphs; smaller graphs keep NETWORK_SIMPLEX for its tighter layout.
export const LARGE_GRAPH_NODE_THRESHOLD = 150

type LayoutNode = ReactFlowNode<{ handles?: NodeHandle[] } & Record<string, unknown>>

const getElkPortSide = (position: Position): string => {
    switch (position) {
        case Position.Top:
            return 'NORTH'
        case Position.Bottom:
            return 'SOUTH'
        case Position.Left:
            return 'WEST'
        case Position.Right:
            return 'EAST'
    }
}

export const getFormattedNodes = async <T extends LayoutNode>(
    nodes: T[],
    edges: Edge[],
    direction?: ElkDirection
): Promise<T[]> => {
    if (nodes.length === 0) {
        return []
    }

    direction ??= 'DOWN'
    const nodePlacementStrategy = nodes.length > LARGE_GRAPH_NODE_THRESHOLD ? 'BRANDES_KOEPF' : 'NETWORK_SIMPLEX'
    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.direction': direction,
        'elk.edgeRouting': 'ORTHOGONAL',
        'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
        'elk.layered.cycleBreaking.strategy': 'GREEDY',
        'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
        'elk.layered.mergeEdges': 'true',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        'elk.layered.nodePlacement.strategy': nodePlacementStrategy,
        'elk.layered.spacing.nodeNodeBetweenLayers': '60',
        'elk.padding': '[left=0, top=0, right=0, bottom=0]',
        'elk.separateConnectedComponents': 'true',
        'elk.spacing.edgeNode': '30',
        'elk.spacing.nodeNode': '30',
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: elkOptions,
        children: nodes.map((node) => {
            const handles =
                node.data.handles
                    ?.sort((a, b) => (a.id || '').localeCompare(b.id || ''))
                    .map((h) => ({
                        id: h.id || `${node.id}_${h.type}`,
                        properties: {
                            side: getElkPortSide(h.position),
                        },
                    })) || []

            return {
                ...node,
                width: node.width,
                height: node.height,
                targetPosition: direction === 'DOWN' ? 'top' : 'left',
                sourcePosition: direction === 'DOWN' ? 'bottom' : 'right',
                ports: [...handles],
            }
        }),
        edges: edges.map((edge) => ({
            ...edge,
            id: edge.id,
            sources: [edge.sourceHandle || edge.source],
            targets: [edge.targetHandle || edge.target],
        })) as ElkExtendedEdge[],
    }

    const elk = await getElk()
    const laidOutGraph = await elk.layout(graph)
    return (laidOutGraph.children?.map((node) => ({
        ...node,
        position: { x: node.x, y: node.y },
    })) ?? []) as unknown as T[]
}
