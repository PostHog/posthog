import {
    Edge,
    EdgeChange,
    Node,
    NodeChange,
    Position,
    ReactFlowInstance,
    applyEdgeChanges,
    applyNodeChanges,
} from '@xyflow/react'
import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import type { RefObject } from 'react'

import api from 'lib/api'

import { DataModelingNode } from '~/types'

import { getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, TOP_HANDLE_POSITION } from './constants'
import type { dataModelingEditorLogicType } from './dataModelingEditorLogicType'
import { ModelNode, ModelNodeHandle } from './types'

export const dataModelingEditorLogic = kea<dataModelingEditorLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'modeling', 'dataModelingEditorLogic']),
    actions({
        onEdgesChange: (edges: EdgeChange<Edge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<ModelNode>[]) => ({ nodes }),
        onNodesDelete: (deleted: ModelNode[]) => ({ deleted }),
        setNodes: (nodes: ModelNode[]) => ({ nodes }),
        setNodesRaw: (nodes: ModelNode[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        setReactFlowWrapper: (reactFlowWrapper: RefObject<HTMLDivElement>) => ({ reactFlowWrapper }),
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
            // for now matview nodes only
            const matviewNodes = dataModelingNodes.filter((n) => n.type === 'matview')
            const handlesByNodeId: Record<string, Record<string, ModelNodeHandle>> = {}
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
            // for now empty edges
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
