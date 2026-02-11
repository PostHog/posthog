import { Edge, MarkerType, Node } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'
import { FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import type { funnelFlowGraphLogicType } from './funnelFlowGraphLogicType'

export const NODE_HEIGHT = 160
export const NODE_WIDTH = 300
export const ELK_OPTIONS = {
    'elk.algorithm': 'layered',
    'elk.direction': 'RIGHT',
    'elk.layered.spacing.nodeNodeBetweenLayers': '140',
    'elk.spacing.nodeNode': '40',
    'elk.spacing.edgeEdge': '30',
    'elk.spacing.edgeNode': '30',
    'elk.layered.nodePlacement.strategy': 'SIMPLE',
    'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    'elk.padding': '[left=0, top=0, right=0, bottom=0]',
}

export interface FunnelFlowNodeData extends Record<string, unknown> {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    isOptional: boolean
}

export interface FunnelFlowEdgeData extends Record<string, unknown> {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
}

const elk = new ELK()

const DEFAULT_LOGIC_KEY = 'default_funnel_flow_graph'

async function layoutNodes(nodes: Node<FunnelFlowNodeData>[], edges: Edge[]): Promise<Node<FunnelFlowNodeData>[]> {
    if (nodes.length === 0) {
        return []
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: ELK_OPTIONS,
        children: nodes.map((node) => ({
            id: node.id,
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
            ports: [
                { id: `${node.id}-target`, properties: { side: 'WEST' } },
                { id: `${node.id}-source`, properties: { side: 'EAST' } },
            ],
            properties: {
                'org.eclipse.elk.portConstraints': 'FIXED_ORDER',
            },
        })),
        edges: edges.map((edge) => ({
            id: edge.id,
            sources: [edge.sourceHandle || edge.source],
            targets: [edge.targetHandle || edge.target],
        })) as ElkExtendedEdge[],
    }

    const laidOutGraph = await elk.layout(graph)
    const positionMap = new Map<string, { x: number; y: number }>()
    for (const child of laidOutGraph.children ?? []) {
        positionMap.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 })
    }

    return nodes.map((node) => ({
        ...node,
        position: positionMap.get(node.id) ?? { x: 0, y: 0 },
    }))
}

export const funnelFlowGraphLogic = kea<funnelFlowGraphLogicType>([
    path((key) => ['scenes', 'funnels', 'FunnelFlowGraph', 'funnelFlowGraphLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [funnelDataLogic(props), ['visibleStepsWithConversionMetrics', 'isStepOptional']],
    })),

    actions({
        setLayoutedNodes: (layoutedNodes: Node<FunnelFlowNodeData>[]) => ({ layoutedNodes }),
    }),

    reducers({
        layoutedNodes: [
            [] as Node<FunnelFlowNodeData>[],
            {
                setLayoutedNodes: (_, { layoutedNodes }) => layoutedNodes,
            },
        ],
    }),

    selectors({
        nodes: [
            (s) => [s.visibleStepsWithConversionMetrics, s.isStepOptional],
            (steps, isStepOptional): Node<FunnelFlowNodeData>[] =>
                steps.map((step, index) => {
                    const optional = isStepOptional(index + 1)
                    return {
                        id: `step-${index}`,
                        type: optional ? 'optional' : 'mandatory',
                        data: { step, stepIndex: index, isOptional: optional },
                        position: { x: 0, y: 0 },
                        draggable: false,
                        connectable: false,
                    }
                }),
        ],
        edges: [
            (s) => [s.nodes],
            (nodes): Edge[] =>
                nodes.slice(0, -1).map((node, index) => {
                    const targetNode = nodes[index + 1]
                    return {
                        id: `edge-${index}`,
                        source: node.id,
                        target: targetNode.id,
                        type: 'funnelFlow',
                        sourceHandle: `${node.id}-source`,
                        targetHandle: `${targetNode.id}-target`,
                        markerEnd: { type: MarkerType.ArrowClosed },
                        deletable: false,
                        data: {
                            step: targetNode.data.step,
                            stepIndex: targetNode.data.stepIndex,
                        },
                    }
                }),
        ],
    }),

    subscriptions(({ actions, values }) => ({
        nodes: async () => {
            const positioned = await layoutNodes(values.nodes, values.edges)
            actions.setLayoutedNodes(positioned)
        },
    })),
])
