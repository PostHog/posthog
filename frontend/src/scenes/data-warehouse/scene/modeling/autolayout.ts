import { Edge, Position } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import type { ModelNode } from './types'

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

export type ElkDirection = 'DOWN' | 'RIGHT'
const elk = new ELK()

export const getFormattedNodes = async (
    nodes: ModelNode[],
    edges: Edge[],
    direction?: ElkDirection
): Promise<ModelNode[]> => {
    if (nodes.length === 0) {
        return []
    }

    direction ??= 'DOWN'
    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': `40`,
        'elk.spacing.nodeNode': '30',
        'elk.spacing.edgeEdge': `30`,
        'elk.spacing.edgeNode': `30`,
        'elk.direction': direction,
        'elk.layered.nodePlacement.strategy': 'SIMPLE',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
        'elk.padding': '[left=0, top=0, right=0, bottom=0]',
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
                targetPosition: 'top',
                sourcePosition: 'bottom',
                properties: {
                    'org.eclipse.elk.portConstraints': 'FIXED_ORDER',
                },
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
    })) ?? []) as ModelNode[]
}
