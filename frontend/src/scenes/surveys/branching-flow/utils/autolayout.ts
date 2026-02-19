import { Edge, Position } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import {
    END_NODE_SIMPLE_HEIGHT,
    END_NODE_SIMPLE_WIDTH,
    NODE_EDGE_GAP,
    NODE_GAP,
    NODE_LAYER_GAP,
    QUESTION_NODE_HEIGHT,
    QUESTION_NODE_WIDTH,
} from '../constants'
import type { SurveyFlowNode } from '../types'

function getElkPortSide(position: Position): string {
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

export async function getLayoutedNodes(nodes: SurveyFlowNode[], edges: Edge[]): Promise<SurveyFlowNode[]> {
    if (nodes.length === 0) {
        return []
    }

    const elkOptions = {
        'elk.algorithm': 'layered',
        'elk.layered.spacing.nodeNodeBetweenLayers': `${NODE_LAYER_GAP}`,
        'elk.spacing.nodeNode': `${NODE_GAP}`,
        'elk.spacing.edgeEdge': `${NODE_EDGE_GAP}`,
        'elk.spacing.edgeNode': `${NODE_EDGE_GAP}`,
        'elk.direction': 'RIGHT',
        'elk.layered.nodePlacement.strategy': 'SIMPLE',
        'elk.alignment': 'CENTER',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
        'elk.padding': '[left=0, top=0, right=0, bottom=0]',
        'elk.edgeLabels.inline': 'false',
        'elk.spacing.edgeLabelSpacing': '4',
        'elk.layered.spacing.edgeNodeBetweenLayers': '20',
        'elk.layered.spacing.edgeEdgeBetweenLayers': '10',
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: elkOptions,
        children: nodes.map((node) => {
            const isEndNode = node.type === 'end'
            const hasThankYouMessage = isEndNode && node.data.survey?.appearance?.displayThankYouMessage

            let width: number
            let height: number

            if (isEndNode && !hasThankYouMessage) {
                width = END_NODE_SIMPLE_WIDTH
                height = END_NODE_SIMPLE_HEIGHT
            } else {
                width = QUESTION_NODE_WIDTH
                height = QUESTION_NODE_HEIGHT
            }

            const sourceHandles = node.type === 'surveyQuestion' ? node.data.sourceHandles : []
            const handles = sourceHandles.map((h, index) => ({
                id: h.id,
                properties: {
                    side: getElkPortSide(Position.Right),
                    index: `${index}`,
                },
            }))

            handles.push({
                id: `${node.id}_target`,
                properties: {
                    side: getElkPortSide(Position.Left),
                    index: '0',
                },
            })

            return {
                ...node,
                width,
                height,
                targetPosition: 'left',
                sourcePosition: 'right',
                properties: {
                    'org.eclipse.elk.portConstraints': 'FIXED_ORDER',
                },
                ports: handles,
            }
        }),
        edges: edges.map((edge) => {
            const elkEdge: ElkExtendedEdge = {
                id: edge.id,
                sources: [edge.sourceHandle || edge.source],
                targets: [`${edge.target}_target`],
            }
            if (edge.label) {
                elkEdge.labels = [
                    {
                        id: `${edge.id}-label`,
                        text: String(edge.label),
                        width: String(edge.label).length * 6 + 8,
                        height: 16,
                    },
                ]
            }
            return elkEdge
        }),
    }

    const layoutedGraph = await elk.layout(graph)

    return (layoutedGraph.children?.map((node) => ({
        ...node,
        position: { x: node.x || 0, y: node.y || 0 },
    })) ?? []) as SurveyFlowNode[]
}
