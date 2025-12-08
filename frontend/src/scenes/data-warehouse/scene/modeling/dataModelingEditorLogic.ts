import {
    Edge,
    EdgeChange,
    MarkerType,
    Node,
    NodeChange,
    Position,
    ReactFlowInstance,
    applyEdgeChanges,
    applyNodeChanges,
} from '@xyflow/react'
import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import type { DragEvent, RefObject } from 'react'

import api from 'lib/api'

import { DataModelingEdge, DataModelingNode, DataModelingNodeType } from '~/types'

import { getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, TOP_HANDLE_POSITION } from './constants'
import type { dataModelingEditorLogicType } from './dataModelingEditorLogicType'
import { CreateModelNodeType, ModelNode, ModelNodeHandle } from './types'

const getEdgeId = (from: string, to: string): string => `${from}->${to}`

export const dataModelingEditorLogic = kea<dataModelingEditorLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'modeling', 'dataModelingEditorLogic']),
    actions({
        onEdgesChange: (edges: EdgeChange<Edge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<ModelNode>[]) => ({ nodes }),
        onNodesDelete: (deleted: ModelNode[]) => ({ deleted }),
        setNodes: (nodes: ModelNode[]) => ({ nodes }),
        setDropzoneNodes: (dropzoneNodes: Node<{ edge: Edge }>[]) => ({ dropzoneNodes }),
        setNodesRaw: (nodes: ModelNode[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        setReactFlowWrapper: (reactFlowWrapper: RefObject<HTMLDivElement>) => ({ reactFlowWrapper }),
        onDragStart: true,
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event: DragEvent) => ({ event }),
        setNewDraggingNode: (newDraggingNode: CreateModelNodeType | null) => ({ newDraggingNode }),
        setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => ({ highlightedDropzoneNodeId }),
        setHighlightedNodeType: (highlightedNodeType: DataModelingNodeType | null) => ({ highlightedNodeType }),
        resetGraph: (dataModelingNodes: DataModelingNode[], dataModelingEdges: DataModelingEdge[]) => ({
            dataModelingNodes,
            dataModelingEdges,
        }),
        runNode: (nodeId: string, direction: 'upstream' | 'downstream') => ({ nodeId, direction }),
        runNodeSuccess: (nodeId: string, direction: 'upstream' | 'downstream') => ({ nodeId, direction }),
        runNodeFailure: (nodeId: string, direction: 'upstream' | 'downstream', error: string) => ({
            nodeId,
            direction,
            error,
        }),
        materializeNode: (nodeId: string) => ({ nodeId }),
        materializeNodeSuccess: (nodeId: string) => ({ nodeId }),
        materializeNodeFailure: (nodeId: string, error: string) => ({ nodeId, error }),
    }),
    loaders({
        dataModelingNodes: [
            [] as DataModelingNode[],
            {
                loadDataModelingNodes: async () => {
                    const response = await api.dataModelingNodes.list()
                    return response.results
                },
            },
        ],
        dataModelingEdges: [
            [] as DataModelingEdge[],
            {
                loadDataModelingEdges: async () => {
                    const response = await api.dataModelingEdges.list()
                    return response.results
                },
            },
        ],
    }),
    reducers(() => ({
        nodes: [
            [] as ModelNode[],
            {
                setNodesRaw: (_, { nodes }) => nodes,
            },
        ],
        dropzoneNodes: [
            [] as Node<{ edge: Edge }>[],
            {
                setDropzoneNodes: (_, { dropzoneNodes }) => dropzoneNodes,
            },
        ],
        highlightedDropzoneNodeId: [
            null as string | null,
            {
                setHighlightedDropzoneNodeId: (_, { highlightedDropzoneNodeId }) => highlightedDropzoneNodeId,
            },
        ],
        highlightedNodeType: [
            null as DataModelingNodeType | null,
            {
                setHighlightedNodeType: (_, { highlightedNodeType }) => highlightedNodeType,
            },
        ],
        edges: [
            [] as Edge[],
            {
                setEdges: (_, { edges }) => edges,
            },
        ],
        selectedNodeId: [
            null as string | null,
            {
                setSelectedNodeId: (_, { selectedNodeId }) => selectedNodeId,
            },
        ],
        newDraggingNode: [
            null as CreateModelNodeType | null,
            {
                setNewDraggingNode: (_, { newDraggingNode }) => newDraggingNode,
            },
        ],
        reactFlowInstance: [
            null as ReactFlowInstance<Node, Edge> | null,
            {
                setReactFlowInstance: (_, { reactFlowInstance }) => reactFlowInstance,
            },
        ],
        reactFlowWrapper: [
            null as RefObject<HTMLDivElement> | null,
            {
                setReactFlowWrapper: (_, { reactFlowWrapper }) => reactFlowWrapper,
            },
        ],
    })),
    selectors({
        nodesById: [
            (s) => [s.nodes],
            (nodes): Record<string, ModelNode> => {
                return nodes.reduce(
                    (acc, node) => {
                        acc[node.id] = node
                        return acc
                    },
                    {} as Record<string, ModelNode>
                )
            },
        ],
        selectedNode: [
            (s) => [s.nodes, s.selectedNodeId],
            (nodes, selectedNodeId) => {
                return nodes.find((node) => node.id === selectedNodeId) ?? null
            },
        ],
        nodesLoading: [
            (s) => [s.dataModelingNodesLoading, s.dataModelingEdgesLoading],
            (dataModelingNodesLoading: boolean, dataModelingEdgesLoading: boolean): boolean =>
                dataModelingNodesLoading || dataModelingEdgesLoading,
        ],
    }),
    listeners(({ values, actions }) => ({
        onEdgesChange: ({ edges }) => {
            actions.setEdges(applyEdgeChanges(edges, values.edges))
        },
        onNodesChange: ({ nodes }) => {
            actions.setNodes(applyNodeChanges(nodes, values.nodes))
        },

        loadDataModelingNodesSuccess: () => {
            if (values.dataModelingEdges.length > 0 || !values.dataModelingEdgesLoading) {
                actions.resetGraph(values.dataModelingNodes, values.dataModelingEdges)
            }
        },

        loadDataModelingEdgesSuccess: () => {
            if (values.dataModelingNodes.length > 0 || !values.dataModelingNodesLoading) {
                actions.resetGraph(values.dataModelingNodes, values.dataModelingEdges)
            }
        },

        resetGraph: async ({ dataModelingNodes, dataModelingEdges }) => {
            const nodeIds = new Set(dataModelingNodes.map((n) => n.id))

            const handlesByNodeId: Record<string, Record<string, ModelNodeHandle>> = {}

            dataModelingNodes.forEach((node) => {
                handlesByNodeId[node.id] = {
                    [`target_${node.id}`]: {
                        id: `target_${node.id}`,
                        type: 'target',
                        position: Position.Top,
                        ...TOP_HANDLE_POSITION,
                    },
                    [`source_${node.id}`]: {
                        id: `source_${node.id}`,
                        type: 'source',
                        position: Position.Bottom,
                        ...BOTTOM_HANDLE_POSITION,
                    },
                }
            })

            const sortedNodes = [...dataModelingNodes].sort((a, b) =>
                a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
            )

            const nodes: ModelNode[] = sortedNodes.map((node) => {
                const userTag = (node.properties?.user as Record<string, unknown>)?.tag as string | undefined
                return {
                    id: node.id,
                    type: 'model',
                    data: {
                        id: node.id,
                        name: node.name,
                        type: node.type,
                        dagId: node.dag_id,
                        savedQueryId: node.saved_query_id,
                        handles: Object.values(handlesByNodeId[node.id] ?? {}),
                        userTag,
                    },
                    position: { x: 0, y: 0 },
                    deletable: true,
                    selectable: true,
                    draggable: false,
                    connectable: false,
                }
            })

            // Build edges from the API data, filtering to only include edges between matview nodes
            const edges: Edge[] = dataModelingEdges
                .filter((edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id))
                .map((edge) => ({
                    id: getEdgeId(edge.source_id, edge.target_id),
                    source: edge.source_id,
                    target: edge.target_id,
                    type: 'smart',
                    deletable: false,
                    markerEnd: { type: MarkerType.ArrowClosed },
                    sourceHandle: `source_${edge.source_id}`,
                    targetHandle: `target_${edge.target_id}`,
                }))

            actions.setEdges(edges)
            actions.setNodes(nodes)
        },

        setNodes: async ({ nodes }) => {
            if (nodes.length === 0) {
                actions.setNodesRaw([])
                return
            }
            const formattedNodes = await getFormattedNodes(nodes, values.edges)
            actions.setNodesRaw(formattedNodes)
        },

        onNodesDelete: ({ deleted }) => {
            if (deleted.some((node) => node.id === values.selectedNodeId)) {
                actions.setSelectedNodeId(null)
            }
        },

        runNode: async ({ nodeId, direction }) => {
            try {
                await api.dataModelingNodes.run(nodeId, direction)
                actions.runNodeSuccess(nodeId, direction)
            } catch (e) {
                actions.runNodeFailure(nodeId, direction, String(e))
            }
        },

        materializeNode: async ({ nodeId }) => {
            try {
                await api.dataModelingNodes.materialize(nodeId)
                actions.materializeNodeSuccess(nodeId)
            } catch (e) {
                actions.materializeNodeFailure(nodeId, String(e))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataModelingNodes()
        actions.loadDataModelingEdges()
    }),
])
