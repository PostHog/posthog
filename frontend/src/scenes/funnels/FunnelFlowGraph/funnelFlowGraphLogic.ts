import { Edge, MarkerType, Node } from '@xyflow/react'
import ELK, { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'
import { FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import type { funnelFlowGraphLogicType } from './funnelFlowGraphLogicType'
import { funnelPathsExpansionLogic } from './funnelPathsExpansionLogic'
import {
    bridgeConfigForExpansion,
    buildPathFlowElements,
    PathFlowEdgeData,
    PATH_NODE_HEIGHT,
    PATH_NODE_WIDTH,
    PathFlowNodeData,
} from './pathFlowUtils'

export const NODE_HEIGHT = 160
export const NODE_WIDTH = 300
export const FIT_VIEW_OPTIONS = {
    padding: 0.2,
    maxZoom: 1,
}

export const PROFILE_NODE_HEIGHT = 80
export const PROFILE_NODE_WIDTH = 180
export const PROFILE_FIT_VIEW_OPTIONS = {
    padding: 0.1,
    maxZoom: 2,
}

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
    edgeIndex: number
}

export type AnyFlowNode = Node<FunnelFlowNodeData> | Node<PathFlowNodeData>

const elk = new ELK()

const DEFAULT_LOGIC_KEY = 'default_funnel_flow_graph'

async function layoutNodes(
    nodes: AnyFlowNode[],
    edges: Edge[],
    elkOptionsOverride?: Record<string, string>,
    elkNodeSize?: { width: number; height: number }
): Promise<AnyFlowNode[]> {
    if (nodes.length === 0) {
        return []
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: { ...ELK_OPTIONS, ...elkOptionsOverride },
        children: nodes.map((node) => {
            const isPathNode = node.type === 'pathNode' || node.type === 'builderPathNode'
            return {
                id: node.id,
                width: isPathNode ? PATH_NODE_WIDTH : (elkNodeSize?.width ?? NODE_WIDTH),
                height: isPathNode ? PATH_NODE_HEIGHT : (elkNodeSize?.height ?? NODE_HEIGHT),
                ports: [
                    { id: `${node.id}-target`, properties: { side: 'WEST' } },
                    { id: `${node.id}-source`, properties: { side: 'EAST' } },
                ],
                properties: {
                    'org.eclipse.elk.portConstraints': 'FIXED_ORDER',
                },
            }
        }),
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

export type FunnelFlowGraphMode = 'profile' | 'builder'

export interface FunnelFlowLogicProps extends InsightLogicProps {
    mode?: FunnelFlowGraphMode
}

export const funnelFlowGraphLogic = kea<funnelFlowGraphLogicType>([
    path((key) => ['scenes', 'funnels', 'FunnelFlowGraph', 'funnelFlowGraphLogic', key]),
    props({} as FunnelFlowLogicProps),
    key(keyForInsightLogicProps(DEFAULT_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            funnelDataLogic(props),
            ['visibleStepsWithConversionMetrics', 'stepNames', 'isStepOptional'],
            funnelPathsExpansionLogic(props),
            ['expandedPath', 'expandedPathResults'],
        ],
    })),

    actions({
        setLaidOutNodes: (laidOutNodes: AnyFlowNode[]) => ({ laidOutNodes }),
    }),

    reducers({
        laidOutNodes: [
            [] as AnyFlowNode[],
            {
                setLaidOutNodes: (_, { laidOutNodes }) => laidOutNodes,
            },
        ],
    }),

    selectors(({}) => ({
        isProfileMode: [() => [(_, props) => props.mode], (mode): boolean => mode === 'profile'],
        nodeType: [
            () => [(_, props) => props.mode],
            (mode): string => (mode === 'profile' ? 'profile' : mode === 'builder' ? 'journeyCreate' : 'journey'),
        ],
        pathNodeType: [
            () => [(_, props) => props.mode],
            (mode): string => (mode === 'builder' ? 'builderPathNode' : 'pathNode'),
        ],
        edgeType: [(s) => [s.isProfileMode], (isProfileMode): string => (isProfileMode ? 'profile' : 'journey')],
        nodeWidth: [
            (s) => [s.isProfileMode],
            (isProfileMode): number => (isProfileMode ? PROFILE_NODE_WIDTH : NODE_WIDTH),
        ],
        nodeHeight: [
            (s) => [s.isProfileMode],
            (isProfileMode): number => (isProfileMode ? PROFILE_NODE_HEIGHT : NODE_HEIGHT),
        ],
        fitViewOptions: [
            (s) => [s.isProfileMode],
            (isProfileMode) => (isProfileMode ? PROFILE_FIT_VIEW_OPTIONS : FIT_VIEW_OPTIONS),
        ],
        funnelNodes: [
            (s) => [
                s.visibleStepsWithConversionMetrics,
                s.stepNames,
                s.isStepOptional,
                s.nodeType,
                s.nodeWidth,
                s.nodeHeight,
            ],
            (steps, stepNames, isStepOptional, nodeType, nodeWidth, nodeHeight): Node<FunnelFlowNodeData>[] => {
                const stepsToMap: FunnelStepWithConversionMetrics[] =
                    steps.length > 0
                        ? steps
                        : stepNames.map(({ nested_breakdown: _, ...s }) => ({
                              ...s,
                              droppedOffFromPrevious: 0,
                              conversionRates: { fromPrevious: 0, total: 0, fromBasisStep: 0 },
                          }))
                return stepsToMap.map((step, index) => {
                    const optional = isStepOptional(index + 1)
                    return {
                        id: `step-${index}`,
                        type: nodeType,
                        data: { step, stepIndex: index, isOptional: optional },
                        position: { x: 0, y: 0 },
                        width: nodeWidth,
                        height: nodeHeight,
                        draggable: false,
                        connectable: false,
                    }
                })
            },
        ],
        funnelEdges: [
            (s) => [s.funnelNodes, s.edgeType],
            (nodes, edgeType): Edge<FunnelFlowEdgeData>[] =>
                nodes.slice(0, -1).map((node, index) => {
                    const targetNode = nodes[index + 1]
                    const touchesOptionalStep = targetNode.data.isOptional

                    const isProfileMode = edgeType === 'profile'

                    return {
                        id: `edge-${index}`,
                        source: node.id,
                        target: targetNode.id,
                        type: edgeType,
                        sourceHandle: `${node.id}-source`,
                        targetHandle: `${targetNode.id}-target`,
                        markerEnd: {
                            type: MarkerType.ArrowClosed,
                            ...(isProfileMode && { color: 'var(--color-border-secondary)' }),
                        },
                        deletable: false,
                        style: {
                            ...(isProfileMode && {
                                stroke: 'var(--color-border-secondary)',
                                strokeWidth: 2,
                            }),
                            ...(touchesOptionalStep && { strokeDasharray: '5 5' }),
                        },
                        data: {
                            step: targetNode.data.step,
                            stepIndex: targetNode.data.stepIndex,
                            edgeIndex: index,
                        },
                    }
                }),
        ],
        expandedPathElements: [
            (s) => [s.funnelNodes, s.expandedPath, s.expandedPathResults, s.pathNodeType],
            (
                funnelNodes,
                expandedPath,
                expandedPathResults,
                pathNodeType
            ): {
                nodes: Node<PathFlowNodeData>[]
                edges: Edge<PathFlowEdgeData>[]
                hiddenEdgeId: string | null
            } | null => {
                if (!expandedPath || !expandedPathResults) {
                    return null
                }
                const bridgeConfig = bridgeConfigForExpansion(expandedPath)

                const funnelStepByEventName = new Map<string, string>()
                for (const node of funnelNodes) {
                    const eventName = node.data.step.name
                    if (!funnelStepByEventName.has(eventName)) {
                        funnelStepByEventName.set(eventName, node.id)
                    }
                }

                const { nodes, edges } = buildPathFlowElements(
                    expandedPathResults,
                    bridgeConfig.sourceStepId,
                    bridgeConfig.targetStepId,
                    bridgeConfig.isDropOff || undefined,
                    funnelStepByEventName,
                    pathNodeType
                )
                return { nodes, edges, hiddenEdgeId: bridgeConfig.hiddenEdgeId }
            },
        ],
        nodes: [
            (s) => [s.funnelNodes, s.expandedPathElements],
            (funnelNodes, expandedPathElements): AnyFlowNode[] => {
                if (!expandedPathElements) {
                    return funnelNodes
                }
                return [...funnelNodes, ...expandedPathElements.nodes]
            },
        ],
        edges: [
            (s) => [s.funnelEdges, s.expandedPathElements],
            (funnelEdges, expandedPathElements): Edge[] => {
                if (!expandedPathElements) {
                    return funnelEdges
                }
                const visibleFunnelEdges = expandedPathElements.hiddenEdgeId
                    ? funnelEdges.filter((e) => e.id !== expandedPathElements.hiddenEdgeId)
                    : funnelEdges
                return [...visibleFunnelEdges, ...expandedPathElements.edges]
            },
        ],
    })),

    subscriptions(({ actions, values }) => ({
        nodes: async () => {
            const elkOverrides = values.isProfileMode
                ? { 'elk.layered.spacing.nodeNodeBetweenLayers': '40' }
                : undefined
            const elkNodeSize = {
                width: values.nodeWidth,
                height: values.nodeHeight,
            }
            const positioned = await layoutNodes(values.nodes, values.edges, elkOverrides, elkNodeSize)
            actions.setLaidOutNodes(positioned)
        },
    })),
])
