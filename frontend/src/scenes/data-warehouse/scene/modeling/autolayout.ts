import { Edge, Position } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import type { ElkDirection, Node } from './types'

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

const elk = new ELK()

export const getFormattedNodes = async (nodes: Node[], edges: Edge[], direction?: ElkDirection): Promise<Node[]> => {
    if (nodes.length === 0) {
        return []
    }

    direction ??= 'DOWN'
    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.direction': direction,
        'elk.edgeRouting': 'ORTHOGONAL',
        'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
        'elk.layered.cycleBreaking.strategy': 'GREEDY',
        'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
        'elk.layered.mergeEdges': 'true',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
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
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
                targetPosition: direction === 'DOWN' ? 'top' : 'left',
                sourcePosition: direction === 'RIGHT' ? 'bottom' : 'right',
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

    const laidOutGraph = await elk.layout(graph)
    return (laidOutGraph.children?.map((node) => ({
        ...node,
        position: { x: node.x, y: node.y },
    })) ?? []) as Node[]
}
