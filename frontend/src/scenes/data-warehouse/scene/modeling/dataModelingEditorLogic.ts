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
import equal from 'fast-deep-equal'
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

import { ElkDirection, getFormattedNodes } from './autolayout'
import { BOTTOM_HANDLE_POSITION, LEFT_HANDLE_POSITION, RIGHT_HANDLE_POSITION, TOP_HANDLE_POSITION } from './constants'
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
        setNodes: (nodes: ModelNode[], fitViewAfter?: boolean) => ({ nodes, fitViewAfter }),
        setNodesRaw: (nodes: ModelNode[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        setReactFlowWrapper: (reactFlowWrapper: RefObject<HTMLDivElement>) => ({ reactFlowWrapper }),
        setHighlightedNodeType: (highlightedNodeType: DataModelingNodeType | null) => ({ highlightedNodeType }),
        resetGraph: (
            dataModelingNodes: DataModelingNode[],
            dataModelingEdges: DataModelingEdge[],
            fitViewAfter?: boolean
        ) => ({
            dataModelingNodes,
            dataModelingEdges,
            fitViewAfter,
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
        setLayoutDirection: (layoutDirection: ElkDirection) => ({ layoutDirection }),
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
        layoutDirection: [
            'DOWN' as ElkDirection,
            {
                setLayoutDirection: (_, { layoutDirection }) => layoutDirection,
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
            { resultEqualityCheck: equal },
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
            { resultEqualityCheck: equal },
        ],
        selectedNode: [
            (s) => [s.nodesById, s.selectedNodeId],
            (nodesById, selectedNodeId) => {
                return selectedNodeId ? (nodesById[selectedNodeId] ?? null) : null
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
            { resultEqualityCheck: equal },
        ],
        // nodes are enriched with derived state to optimize reactflow rendering
        enrichedNodes: [
            (s) => [s.nodes, s.selectedNodeId, s.runningNodeIds, s.lastJobStatusByNodeId, s.highlightedNodeType],
            (nodes, selectedNodeId, runningNodeIds, lastJobStatusByNodeId, highlightedNodeType): ModelNode[] => {
                return nodes.map((node) => {
                    const isSelected = selectedNodeId === node.id
                    const isRunning = runningNodeIds.has(node.id)
                    const lastJobStatus = lastJobStatusByNodeId[node.id]
                    const isTypeHighlighted = highlightedNodeType !== null && highlightedNodeType === node.data.type
                    if (
                        node.data.isSelected === isSelected &&
                        node.data.isRunning === isRunning &&
                        node.data.lastJobStatus === lastJobStatus &&
                        node.data.isTypeHighlighted === isTypeHighlighted
                    ) {
                        return node
                    }
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            isSelected,
                            isRunning,
                            lastJobStatus,
                            isTypeHighlighted,
                        },
                    }
                })
            },
        ],
        highlightedNodeIds: [
            (s) => [s.nodes, s.edges],
            (nodes, edges): ((baseName: string, mode: 'upstream' | 'downstream' | 'all') => Set<string>) => {
                // Build adjacency lists for efficient traversal
                const upstreamEdges = new Map<string, string[]>() // target -> sources
                const downstreamEdges = new Map<string, string[]>() // source -> targets

                for (const edge of edges) {
                    // upstream: edge.source is upstream of edge.target
                    if (!upstreamEdges.has(edge.target)) {
                        upstreamEdges.set(edge.target, [])
                    }
                    upstreamEdges.get(edge.target)!.push(edge.source)

                    // downstream: edge.target is downstream of edge.source
                    if (!downstreamEdges.has(edge.source)) {
                        downstreamEdges.set(edge.source, [])
                    }
                    downstreamEdges.get(edge.source)!.push(edge.target)
                }

                // BFS helper to traverse in one direction
                const traverse = (startId: string, adjacencyMap: Map<string, string[]>): Set<string> => {
                    const result = new Set<string>()
                    const queue = [startId]
                    while (queue.length > 0) {
                        const current = queue.shift()!
                        const neighbors = adjacencyMap.get(current) ?? []
                        for (const neighbor of neighbors) {
                            if (!result.has(neighbor)) {
                                result.add(neighbor)
                                queue.push(neighbor)
                            }
                        }
                    }
                    return result
                }

                return (baseName: string, mode: 'upstream' | 'downstream' | 'all'): Set<string> => {
                    // Find the starting node by name (exact match first, then partial)
                    const lowerBaseName = baseName.toLowerCase()
                    let startNode = nodes.find((n) => n.data.name.toLowerCase() === lowerBaseName)
                    if (!startNode) {
                        startNode = nodes.find((n) => n.data.name.toLowerCase().includes(lowerBaseName))
                    }
                    if (!startNode) {
                        return new Set()
                    }

                    const result = new Set<string>([startNode.id])

                    if (mode === 'upstream' || mode === 'all') {
                        for (const id of traverse(startNode.id, upstreamEdges)) {
                            result.add(id)
                        }
                    }
                    if (mode === 'downstream' || mode === 'all') {
                        for (const id of traverse(startNode.id, downstreamEdges)) {
                            result.add(id)
                        }
                    }

                    return result
                }
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

        resetGraph: async ({ dataModelingNodes, dataModelingEdges, fitViewAfter }) => {
            const nodeIds = new Set(dataModelingNodes.map((n) => n.id))
            const isHorizontal = values.layoutDirection === 'RIGHT'

            const handlesByNodeId: Record<string, Record<string, ModelNodeHandle>> = {}

            dataModelingNodes.forEach((node) => {
                handlesByNodeId[node.id] = {
                    [`target_${node.id}`]: {
                        id: `target_${node.id}`,
                        type: 'target',
                        position: isHorizontal ? Position.Left : Position.Top,
                        ...(isHorizontal ? LEFT_HANDLE_POSITION : TOP_HANDLE_POSITION),
                    },
                    [`source_${node.id}`]: {
                        id: `source_${node.id}`,
                        type: 'source',
                        position: isHorizontal ? Position.Right : Position.Bottom,
                        ...(isHorizontal ? RIGHT_HANDLE_POSITION : BOTTOM_HANDLE_POSITION),
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
                        upstreamCount: node.upstream_count,
                        downstreamCount: node.downstream_count,
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
                    type: 'straight',
                    deletable: false,
                    markerEnd: { type: MarkerType.ArrowClosed },
                    sourceHandle: `source_${edge.source_id}`,
                    targetHandle: `target_${edge.target_id}`,
                }))

            actions.setEdges(edges)
            actions.setNodes(nodes, fitViewAfter)
        },

        setNodes: async ({ nodes, fitViewAfter }) => {
            if (nodes.length === 0) {
                actions.setNodesRaw([])
                return
            }
            const formattedNodes = await getFormattedNodes(nodes, values.edges, values.layoutDirection)
            actions.setNodesRaw(formattedNodes)
            if (fitViewAfter) {
                values.reactFlowInstance?.fitView({ padding: 0.2, maxZoom: 1 })
            }
        },

        onNodesDelete: ({ deleted }) => {
            if (deleted.some((node) => node.id === values.selectedNodeId)) {
                actions.setSelectedNodeId(null)
            }
        },

        setLayoutDirection: () => {
            if (values.dataModelingNodes.length > 0) {
                actions.resetGraph(values.dataModelingNodes, values.dataModelingEdges, true)
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
