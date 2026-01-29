import { Edge, Position } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { NODE_EDGE_GAP, NODE_GAP, NODE_HEIGHT, NODE_LAYER_GAP, NODE_WIDTH } from './constants'
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

const elk = new ELK()

export const getFormattedNodes = async (nodes: ModelNode[], edges: Edge[]): Promise<ModelNode[]> => {
    if (nodes.length === 0) {
        return []
    }

    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': `${NODE_LAYER_GAP}`,
        'elk.spacing.nodeNode': `${NODE_GAP}`,
        'elk.spacing.edgeEdge': `${NODE_EDGE_GAP}`,
        'elk.spacing.edgeNode': `${NODE_EDGE_GAP}`,
        'elk.direction': 'DOWN',
        'elk.layered.nodePlacement.strategy': 'SIMPLE',
        'elk.alignment': 'CENTER',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        'elk.padding': '[left=0, top=0, right=0, bottom=0]',
        'elk.layered.crossingMinimization.forceNodeModelOrder': 'true',
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
