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
import { uuid } from 'lib/utils'

import { DataModelingNode } from '~/types'

import { getSmartStepPath } from './SmartEdge'
import { getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, NODE_HEIGHT, NODE_WIDTH, TOP_HANDLE_POSITION } from './constants'
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
        resetGraphFromNodes: (dataModelingNodes: DataModelingNode[]) => ({ dataModelingNodes }),
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
        nodesLoading: [(s) => [s.dataModelingNodesLoading], (dataModelingNodesLoading) => dataModelingNodesLoading],
    }),
    listeners(({ values, actions }) => ({
        onEdgesChange: ({ edges }) => {
            actions.setEdges(applyEdgeChanges(edges, values.edges))
        },
        onNodesChange: ({ nodes }) => {
            actions.setNodes(applyNodeChanges(nodes, values.nodes))
        },

        loadDataModelingNodesSuccess: ({ dataModelingNodes }) => {
            actions.resetGraphFromNodes(dataModelingNodes)
        },

        resetGraphFromNodes: async ({ dataModelingNodes }) => {
            // Build edges from the upstream/downstream relationships
            // For now, we'll create a simple graph with matviews only
            const matviewNodes = dataModelingNodes.filter((n) => n.type === 'matview')

            const handlesByNodeId: Record<string, Record<string, ModelNodeHandle>> = {}

            // Initialize handles for each node
            matviewNodes.forEach((node) => {
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

            const nodes: ModelNode[] = matviewNodes.map((node) => ({
                id: node.id,
                type: 'model',
                data: {
                    id: node.id,
                    name: node.name,
                    type: node.type,
                    dagId: node.dag_id,
                    handles: Object.values(handlesByNodeId[node.id] ?? {}),
                },
                position: { x: 0, y: 0 },
                deletable: true,
                selectable: true,
                draggable: false,
                connectable: false,
            }))

            // For now, edges will be empty since we don't have explicit edge data
            // In a real implementation, you would derive edges from the upstream/downstream counts
            const edges: Edge[] = []

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

        onDragStart: () => {
            const { nodes, edges } = values

            const dropzoneNodes: Node<{ edge: Edge }>[] = []

            // Create dropzones on each edge
            edges.forEach((edge) => {
                const sourceNode = nodes.find((n) => n.id === edge.source)
                const targetNode = nodes.find((n) => n.id === edge.target)

                if (sourceNode && targetNode) {
                    const sourceHandle = sourceNode.data.handles?.find((h) => h.id === edge.sourceHandle)
                    const targetHandle = targetNode.data.handles?.find((h) => h.id === edge.targetHandle)

                    const [, labelX, labelY] = getSmartStepPath({
                        sourceX: sourceNode.position.x + (sourceHandle?.x || 0),
                        sourceY: sourceNode.position.y + (sourceHandle?.y || 0),
                        targetX: targetNode.position.x + (targetHandle?.x || 0),
                        targetY: targetNode.position.y + (targetHandle?.y || 0),
                        edges,
                        currentEdgeId: edge.id,
                    })

                    dropzoneNodes.push({
                        id: `dropzone_edge_${edge.id}`,
                        type: 'dropzone',
                        position: { x: labelX - NODE_WIDTH / 2, y: labelY - NODE_HEIGHT / 2 },
                        data: {
                            edge,
                        },
                        draggable: false,
                        selectable: false,
                    })
                }
            })

            // Also create a dropzone at a default position if there are no edges but there are nodes
            if (dropzoneNodes.length === 0 && nodes.length > 0) {
                const lastNode = nodes[nodes.length - 1]
                dropzoneNodes.push({
                    id: `dropzone_new`,
                    type: 'dropzone',
                    position: {
                        x: lastNode.position.x,
                        y: lastNode.position.y + NODE_HEIGHT + 50,
                    },
                    data: {
                        edge: { id: 'new', source: lastNode.id, target: 'new' },
                    },
                    draggable: false,
                    selectable: false,
                })
            }

            // If there are no nodes, create a single dropzone in the center
            if (nodes.length === 0) {
                dropzoneNodes.push({
                    id: `dropzone_center`,
                    type: 'dropzone',
                    position: { x: 0, y: 0 },
                    data: {
                        edge: { id: 'center', source: '', target: '' },
                    },
                    draggable: false,
                    selectable: false,
                })
            }

            actions.setDropzoneNodes(dropzoneNodes)
        },

        onDragOver: ({ event }) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
        },

        onDrop: ({ event }) => {
            event.preventDefault()
            const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)

            if (values.newDraggingNode && dropzoneNode) {
                const partialNewNode = values.newDraggingNode

                const newNodeId = `node_${partialNewNode.type}_${uuid()}`

                const newNode: ModelNode = {
                    id: newNodeId,
                    type: 'model',
                    data: {
                        id: newNodeId,
                        name: partialNewNode.name,
                        type: partialNewNode.type,
                        handles: [
                            {
                                id: `target_${newNodeId}`,
                                type: 'target',
                                position: Position.Top,
                                ...TOP_HANDLE_POSITION,
                            },
                            {
                                id: `source_${newNodeId}`,
                                type: 'source',
                                position: Position.Bottom,
                                ...BOTTOM_HANDLE_POSITION,
                            },
                        ],
                    },
                    position: dropzoneNode.position,
                    deletable: true,
                    selectable: true,
                    draggable: false,
                    connectable: false,
                }

                const edgeData = dropzoneNode.data.edge

                // Create new edges if we're inserting between existing nodes
                const newEdges: Edge[] = [...values.edges]

                if (edgeData.source && edgeData.target && edgeData.id !== 'new' && edgeData.id !== 'center') {
                    // Remove the old edge
                    const edgeIndex = newEdges.findIndex((e) => e.id === edgeData.id)
                    if (edgeIndex !== -1) {
                        newEdges.splice(edgeIndex, 1)
                    }

                    // Add edge from source to new node
                    newEdges.push({
                        id: getEdgeId(edgeData.source, newNodeId),
                        source: edgeData.source,
                        target: newNodeId,
                        type: 'smart',
                        deletable: false,
                        markerEnd: { type: MarkerType.ArrowClosed },
                        sourceHandle: `source_${edgeData.source}`,
                        targetHandle: `target_${newNodeId}`,
                    })

                    // Add edge from new node to target
                    newEdges.push({
                        id: getEdgeId(newNodeId, edgeData.target),
                        source: newNodeId,
                        target: edgeData.target,
                        type: 'smart',
                        deletable: false,
                        markerEnd: { type: MarkerType.ArrowClosed },
                        sourceHandle: `source_${newNodeId}`,
                        targetHandle: `target_${edgeData.target}`,
                    })
                } else if (edgeData.source && edgeData.id === 'new') {
                    // Adding after the last node
                    newEdges.push({
                        id: getEdgeId(edgeData.source, newNodeId),
                        source: edgeData.source,
                        target: newNodeId,
                        type: 'smart',
                        deletable: false,
                        markerEnd: { type: MarkerType.ArrowClosed },
                        sourceHandle: `source_${edgeData.source}`,
                        targetHandle: `target_${newNodeId}`,
                    })
                }
                // If it's the center dropzone, just add the node without edges

                actions.setEdges(newEdges)
                actions.setNodes([...values.nodes, newNode])
                actions.setNewDraggingNode(null)
                actions.setSelectedNodeId(newNodeId)
            }

            actions.setDropzoneNodes([])
        },

        setReactFlowInstance: () => {
            setTimeout(() => {
                values.reactFlowInstance?.fitView({ duration: 0 })
            }, 100)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataModelingNodes()
    }),
])
