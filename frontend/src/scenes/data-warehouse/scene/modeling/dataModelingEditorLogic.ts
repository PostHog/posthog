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
import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import type { RefObject } from 'react'

import api from 'lib/api'

import {
    DataModelingEdge,
    DataModelingJob,
    DataModelingJobStatus,
    DataModelingNode,
    DataModelingNodeType,
} from '~/types'

import { getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, TOP_HANDLE_POSITION } from './constants'
import type { dataModelingEditorLogicType } from './dataModelingEditorLogicType'
import { ModelNode, ModelNodeHandle } from './types'

const POLL_INTERVAL_MS = 2000
const MIN_RUNNING_DURATION_MS = 2000

let pollIntervalId: ReturnType<typeof setInterval> | null = null
const nodeStartTimes: Map<string, number> = new Map()

const getEdgeId = (from: string, to: string): string => `${from}->${to}`

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
        setHighlightedNodeType: (highlightedNodeType: DataModelingNodeType | null) => ({ highlightedNodeType }),
        resetGraph: (dataModelingNodes: DataModelingNode[], dataModelingEdges: DataModelingEdge[]) => ({
            dataModelingNodes,
            dataModelingEdges,
        }),
        runNode: (nodeId: string, direction: 'upstream' | 'downstream') => ({ nodeId, direction }),
        runNodeSuccess: (nodeId: string, direction: 'upstream' | 'downstream', runningNodeIds: string[]) => ({
            nodeId,
            direction,
            runningNodeIds,
        }),
        runNodeFailure: (nodeId: string, direction: 'upstream' | 'downstream', error: string) => ({
            nodeId,
            direction,
            error,
        }),
        materializeNode: (nodeId: string) => ({ nodeId }),
        materializeNodeSuccess: (nodeId: string) => ({ nodeId }),
        materializeNodeFailure: (nodeId: string, error: string) => ({ nodeId, error }),
        setRunningNodeIds: (runningNodeIds: Set<string>) => ({ runningNodeIds }),
        startPollingRunningJobs: true,
        stopPollingRunningJobs: true,
        pollRunningJobs: true,
        pollRunningJobsSuccess: (runningJobs: DataModelingJob[]) => ({ runningJobs }),
        loadRecentJobs: true,
        loadRecentJobsSuccess: (recentJobs: DataModelingJob[]) => ({ recentJobs }),
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
        runningNodeIds: [
            new Set<string>(),
            {
                setRunningNodeIds: (_, { runningNodeIds }) => {
                    for (const nodeId of nodeStartTimes.keys()) {
                        if (!runningNodeIds.has(nodeId)) {
                            nodeStartTimes.delete(nodeId)
                        }
                    }
                    return runningNodeIds
                },
                runNodeSuccess: (state, { runningNodeIds }) => {
                    const now = Date.now()
                    for (const nodeId of runningNodeIds) {
                        if (!nodeStartTimes.has(nodeId)) {
                            nodeStartTimes.set(nodeId, now)
                        }
                    }
                    return new Set([...state, ...runningNodeIds])
                },
                materializeNode: (state, { nodeId }) => {
                    if (!nodeStartTimes.has(nodeId)) {
                        nodeStartTimes.set(nodeId, Date.now())
                    }
                    return new Set([...state, nodeId])
                },
            },
        ],
        lastJobStatusBySavedQueryId: [
            {} as Record<string, DataModelingJobStatus>,
            {
                loadRecentJobsSuccess: (_, { recentJobs }) => {
                    const statusMap: Record<string, DataModelingJobStatus> = {}
                    for (const job of recentJobs) {
                        if (!(job.saved_query_id in statusMap)) {
                            statusMap[job.saved_query_id] = job.status
                        }
                    }
                    return statusMap
                },
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
        nodeIdBySavedQueryId: [
            (s) => [s.nodes],
            (nodes): Record<string, string> => {
                return nodes.reduce(
                    (acc, node) => {
                        if (node.data.savedQueryId) {
                            acc[node.data.savedQueryId] = node.id
                        }
                        return acc
                    },
                    {} as Record<string, string>
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
        lastJobStatusByNodeId: [
            (s) => [s.nodes, s.lastJobStatusBySavedQueryId],
            (nodes, lastJobStatusBySavedQueryId): Record<string, DataModelingJobStatus> => {
                const statusMap: Record<string, DataModelingJobStatus> = {}
                for (const node of nodes) {
                    if (node.data.savedQueryId && lastJobStatusBySavedQueryId[node.data.savedQueryId]) {
                        statusMap[node.id] = lastJobStatusBySavedQueryId[node.data.savedQueryId]
                    }
                }
                return statusMap
            },
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

            const edges: Edge[] = dataModelingEdges
                .filter((edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id))
                .map((edge) => ({
                    id: getEdgeId(edge.source_id, edge.target_id),
                    source: edge.source_id,
                    target: edge.target_id,
                    type: 'bezier',
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
                const response = await api.dataModelingNodes.run(nodeId, direction)
                actions.runNodeSuccess(nodeId, direction, response.node_ids)
                actions.startPollingRunningJobs()
            } catch (e) {
                actions.runNodeFailure(nodeId, direction, String(e))
            }
        },

        materializeNode: async ({ nodeId }) => {
            try {
                await api.dataModelingNodes.materialize(nodeId)
                actions.materializeNodeSuccess(nodeId)
                actions.startPollingRunningJobs()
            } catch (e) {
                actions.materializeNodeFailure(nodeId, String(e))
            }
        },

        pollRunningJobs: async () => {
            try {
                const [running, recent] = await Promise.all([
                    api.dataModelingJobs.listRunning(),
                    api.dataModelingJobs.listRecent(),
                ])
                actions.pollRunningJobsSuccess(running)
                actions.loadRecentJobsSuccess(recent)
            } catch {
                // Keep stale data during transient failures
            }
        },

        pollRunningJobsSuccess: ({ runningJobs }) => {
            const now = Date.now()
            const runningSavedQueryIds = new Set(runningJobs.map((job) => job.saved_query_id))
            const newRunningNodeIds = new Set<string>()

            for (const [savedQueryId, nodeId] of Object.entries(values.nodeIdBySavedQueryId)) {
                if (runningSavedQueryIds.has(savedQueryId)) {
                    newRunningNodeIds.add(nodeId)
                }
            }
            for (const nodeId of values.runningNodeIds) {
                const startTime = nodeStartTimes.get(nodeId)
                if (startTime && now - startTime < MIN_RUNNING_DURATION_MS) {
                    newRunningNodeIds.add(nodeId)
                }
            }
            actions.setRunningNodeIds(newRunningNodeIds)
            if (newRunningNodeIds.size === 0) {
                actions.stopPollingRunningJobs()
            }
        },

        startPollingRunningJobs: () => {
            if (pollIntervalId) {
                return
            }
            actions.pollRunningJobs()
            pollIntervalId = setInterval(() => {
                actions.pollRunningJobs()
            }, POLL_INTERVAL_MS)
        },

        stopPollingRunningJobs: () => {
            if (pollIntervalId) {
                clearInterval(pollIntervalId)
                pollIntervalId = null
                actions.loadRecentJobs()
            }
        },

        loadRecentJobs: async () => {
            try {
                const recentJobs = await api.dataModelingJobs.listRecent()
                actions.loadRecentJobsSuccess(recentJobs)
            } catch {
                // Silently fail
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataModelingNodes()
        actions.loadDataModelingEdges()
        actions.startPollingRunningJobs()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPollingRunningJobs()
    }),
])
