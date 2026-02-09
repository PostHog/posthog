import {
    EdgeChange,
    MarkerType,
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

import type { dataModelingLogicType } from './dataModelingLogicType'
import { getFormattedNodes } from './modeling/autolayout'
import { PAGE_SIZE } from './modeling/constants'
import { Edge, ElkDirection, Node, NodeHandle, SearchMode, ViewMode } from './modeling/types'

const POLL_INTERVAL_MS = 5000
const MIN_RUNNING_DURATION_MS = 2000

let pollIntervalId: ReturnType<typeof setInterval> | null = null
const nodeStartTimes: Map<string, number> = new Map()

const getEdgeId = (from: string, to: string): string => `${from}->${to}`

interface AdjacencyMaps {
    upstream: Map<string, string[]>
    downstream: Map<string, string[]>
}

function buildAdjacencyMaps(edges: Edge[]): AdjacencyMaps {
    const upstream = new Map<string, string[]>()
    const downstream = new Map<string, string[]>()
    for (const edge of edges) {
        if (!upstream.has(edge.target)) {
            upstream.set(edge.target, [])
        }
        upstream.get(edge.target)!.push(edge.source)
        if (!downstream.has(edge.source)) {
            downstream.set(edge.source, [])
        }
        downstream.get(edge.source)!.push(edge.target)
    }
    return { upstream, downstream }
}

function traverseGraph(startId: string, adjacencyMap: Map<string, string[]>): Set<string> {
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

export interface ParsedSearch {
    mode: SearchMode
    baseName: string
}

/** Parse search term for +name (upstream), name+ (downstream), or +name+ (both) syntax */
export function parseSearchTerm(searchTerm: string): ParsedSearch {
    const trimmed = searchTerm.trim()
    if (trimmed.startsWith('+') && trimmed.endsWith('+') && trimmed.length > 2) {
        return { mode: 'all', baseName: trimmed.slice(1, -1) }
    }
    if (trimmed.startsWith('+') && trimmed.length > 1) {
        return { mode: 'upstream', baseName: trimmed.slice(1) }
    }
    if (trimmed.endsWith('+') && trimmed.length > 1) {
        return { mode: 'downstream', baseName: trimmed.slice(0, -1) }
    }
    return { mode: 'search', baseName: trimmed }
}

export const dataModelingLogic = kea<dataModelingLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'dataModelingLogic']),
    actions({
        onEdgesChange: (edges: EdgeChange<Edge>[]) => ({ edges }),
        onNodesChange: (nodes: NodeChange<Node>[]) => ({ nodes }),
        setNodes: (nodes: Node[], fitViewAfter?: boolean) => ({ nodes, fitViewAfter }),
        setNodesRaw: (nodes: Node[]) => ({ nodes }),
        setEdges: (edges: Edge[]) => ({ edges }),
        setReactFlowInstance: (reactFlowInstance: ReactFlowInstance<Node, Edge>) => ({
            reactFlowInstance,
        }),
        setReactFlowWrapper: (reactFlowWrapper: RefObject<HTMLDivElement>) => ({ reactFlowWrapper }),
        setHighlightedNodeType: (highlightedNodeType: DataModelingNodeType | null) => ({ highlightedNodeType }),
        setHoveredNodeId: (hoveredNodeId: string | null) => ({ hoveredNodeId }),
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
        // View/filter actions (previously in dataModelingNodesLogic)
        setViewMode: (viewMode: ViewMode) => ({ viewMode }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setDebouncedSearchTerm: (debouncedSearchTerm: string) => ({ debouncedSearchTerm }),
        setCurrentPage: (page: number) => ({ page }),
        toggleFilterDagId: (dagId: string) => ({ dagId }),
        clearFilterDagIds: true,
        toggleFilterType: (nodeType: DataModelingNodeType) => ({ nodeType }),
        clearFilterTypes: true,
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
            [] as Node[],
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
        hoveredNodeId: [
            null as string | null,
            {
                setHoveredNodeId: (_, { hoveredNodeId }) => hoveredNodeId,
            },
        ],
        edges: [
            [] as Edge[],
            {
                setEdges: (_, { edges }) => edges,
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
        layoutDirection: [
            'RIGHT' as ElkDirection,
            { persist: true },
            {
                setLayoutDirection: (_, { layoutDirection }) => layoutDirection,
            },
        ],
        viewMode: [
            'graph' as ViewMode,
            { persist: true },
            {
                setViewMode: (_, { viewMode }) => viewMode,
            },
        ],
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        debouncedSearchTerm: [
            '' as string,
            {
                setDebouncedSearchTerm: (_, { debouncedSearchTerm }) => debouncedSearchTerm,
            },
        ],
        currentPage: [
            1 as number,
            {
                setCurrentPage: (_, { page }) => page,
                setSearchTerm: () => 1,
                toggleFilterDagId: () => 1,
                clearFilterDagIds: () => 1,
                toggleFilterType: () => 1,
                clearFilterTypes: () => 1,
            },
        ],
        filterDagIds: [
            [] as string[],
            {
                toggleFilterDagId: (state, { dagId }) =>
                    state.includes(dagId) ? state.filter((id) => id !== dagId) : [...state, dagId],
                clearFilterDagIds: () => [],
            },
        ],
        filterTypes: [
            [] as DataModelingNodeType[],
            {
                toggleFilterType: (state, { nodeType }) =>
                    state.includes(nodeType) ? state.filter((t) => t !== nodeType) : [...state, nodeType],
                clearFilterTypes: () => [],
            },
        ],
        latestJobMetadataBySavedQueryId: [
            {} as Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }>,
            {
                loadRecentJobsSuccess: (state, { recentJobs }) => {
                    const map: Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }> = {}
                    for (const job of recentJobs) {
                        if (job.saved_query_id) {
                            map[job.saved_query_id] = {
                                status: job.status,
                                lastRunAt: job.last_run_at,
                            }
                        }
                    }
                    return equal(state, map) ? state : map
                },
            },
        ],
    })),
    selectors({
        nodesById: [
            (s) => [s.nodes],
            (nodes): Record<string, Node> => {
                return nodes.reduce(
                    (acc, node) => {
                        acc[node.id] = node
                        return acc
                    },
                    {} as Record<string, Node>
                )
            },
            { resultEqualityCheck: equal },
        ],
        nodesLoading: [
            (s) => [s.dataModelingNodesLoading, s.dataModelingEdgesLoading],
            (dataModelingNodesLoading: boolean, dataModelingEdgesLoading: boolean): boolean =>
                dataModelingNodesLoading || dataModelingEdgesLoading,
        ],
        latestJobMetadataByNodeId: [
            (s) => [s.nodes, s.latestJobMetadataBySavedQueryId],
            (
                nodes,
                latestJobMetadataBySavedQueryId
            ): Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }> => {
                const map: Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }> = {}
                for (const node of nodes) {
                    if (node.data.savedQueryId && latestJobMetadataBySavedQueryId[node.data.savedQueryId]) {
                        map[node.id] = latestJobMetadataBySavedQueryId[node.data.savedQueryId]
                    }
                }
                return map
            },
            { resultEqualityCheck: equal },
        ],
        enrichedNodes: [
            (s) => [s.nodes, s.runningNodeIds, s.highlightedNodeType, s.latestJobMetadataByNodeId],
            (nodes, runningNodeIds, highlightedNodeType, latestJobMetadataByNodeId): Node[] => {
                return nodes.map((node) => {
                    const isRunning = runningNodeIds.has(node.id)
                    const isTypeHighlighted = highlightedNodeType !== null && highlightedNodeType === node.data.type
                    const metadata = latestJobMetadataByNodeId[node.id]
                    const lastJobStatus = metadata?.status ?? node.data.lastJobStatus
                    const lastRunAt = metadata?.lastRunAt ?? node.data.lastRunAt
                    if (
                        node.data.isRunning === isRunning &&
                        node.data.isTypeHighlighted === isTypeHighlighted &&
                        node.data.lastJobStatus === lastJobStatus &&
                        node.data.lastRunAt === lastRunAt
                    ) {
                        return node
                    }
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            isRunning,
                            isTypeHighlighted,
                            lastJobStatus,
                            lastRunAt,
                        },
                    }
                })
            },
            {
                resultEqualityCheck: (a: Node[], b: Node[]): boolean =>
                    a.length === b.length && a.every((node, i) => node === b[i]),
            },
        ],
        enrichedEdges: [
            (s) => [s.edges, s.hoveredNodeId],
            (edges, hoveredNodeId): Edge[] => {
                if (!hoveredNodeId) {
                    return edges
                }
                return edges.map((edge) => {
                    const isConnected = edge.source === hoveredNodeId || edge.target === hoveredNodeId
                    if (!isConnected) {
                        return edge
                    }
                    return {
                        ...edge,
                        style: { stroke: 'var(--primary-3000)' },
                        markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--primary-3000)' },
                    }
                })
            },
            {
                resultEqualityCheck: (a: Edge[], b: Edge[]): boolean =>
                    a.length === b.length && a.every((edge, i) => edge === b[i]),
            },
        ],
        highlightedNodeIds: [
            (s) => [s.nodes, s.edges],
            (nodes, edges): ((baseName: string, mode: 'upstream' | 'downstream' | 'all') => Set<string>) => {
                const { upstream, downstream } = buildAdjacencyMaps(edges)

                return (baseName: string, mode: 'upstream' | 'downstream' | 'all'): Set<string> => {
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
                        for (const id of traverseGraph(startNode.id, upstream)) {
                            result.add(id)
                        }
                    }
                    if (mode === 'downstream' || mode === 'all') {
                        for (const id of traverseGraph(startNode.id, downstream)) {
                            result.add(id)
                        }
                    }

                    return result
                }
            },
        ],
        // View/filter selectors (previously in dataModelingNodesLogic)
        parsedSearch: [
            (s) => [s.debouncedSearchTerm],
            (debouncedSearchTerm: string): ParsedSearch => parseSearchTerm(debouncedSearchTerm),
        ],
        filteredNodes: [
            (s) => [s.dataModelingNodes, s.searchTerm],
            (dataModelingNodes: DataModelingNode[], searchTerm: string): DataModelingNode[] => {
                if (!searchTerm) {
                    return dataModelingNodes
                }
                const { baseName } = parseSearchTerm(searchTerm)
                return dataModelingNodes.filter((n) => n.name.toLowerCase().includes(baseName.toLowerCase()))
            },
        ],
        availableDagIds: [
            (s) => [s.filteredNodes],
            (nodes: DataModelingNode[]): string[] => {
                const viewableNodes = nodes.filter((n) => n.type === 'matview' || n.type === 'view')
                return [...new Set(viewableNodes.map((n) => n.dag_id))].sort()
            },
        ],
        availableTypes: [
            (s) => [s.filteredNodes],
            (nodes: DataModelingNode[]): DataModelingNodeType[] => {
                const viewableNodes = nodes.filter((n) => n.type === 'matview' || n.type === 'view')
                return [...new Set(viewableNodes.map((n) => n.type))].sort()
            },
        ],
        viewNodes: [
            (s) => [s.filteredNodes, s.filterDagIds, s.filterTypes],
            (
                nodes: DataModelingNode[],
                filterDagIds: string[],
                filterTypes: DataModelingNodeType[]
            ): DataModelingNode[] => {
                return nodes
                    .filter((n) => n.type === 'matview' || n.type === 'view')
                    .filter((n) => filterDagIds.length === 0 || filterDagIds.includes(n.dag_id))
                    .filter((n) => filterTypes.length === 0 || filterTypes.includes(n.type))
            },
        ],
        visibleNodes: [
            (s) => [s.viewNodes, s.currentPage],
            (nodes: DataModelingNode[], currentPage: number): DataModelingNode[] => {
                const startIndex = (currentPage - 1) * PAGE_SIZE
                const endIndex = startIndex + PAGE_SIZE
                return nodes.slice(startIndex, endIndex)
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

            const handlesByNodeId: Record<string, Record<string, NodeHandle>> = {}

            dataModelingNodes.forEach((node) => {
                handlesByNodeId[node.id] = {
                    [`target_${node.id}`]: {
                        id: `target_${node.id}`,
                        type: 'target',
                        position: isHorizontal ? Position.Left : Position.Top,
                    },
                    [`source_${node.id}`]: {
                        id: `source_${node.id}`,
                        type: 'source',
                        position: isHorizontal ? Position.Right : Position.Bottom,
                    },
                }
            })

            const sortedNodes = [...dataModelingNodes].sort((a, b) =>
                a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
            )

            const nodes: Node[] = sortedNodes.map((node) => {
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
                        upstreamCount: node.upstream_count,
                        downstreamCount: node.downstream_count,
                        userTag: node.user_tag,
                        lastJobStatus: node.last_run_status,
                        lastRunAt: node.last_run_at,
                        syncInterval: node.sync_interval,
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
        setLayoutDirection: () => {
            if (values.dataModelingNodes.length > 0) {
                actions.resetGraph(values.dataModelingNodes, values.dataModelingEdges, true)
            }
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm.length > 0) {
                actions.setHighlightedNodeType(null)
            }
            await breakpoint(150)
            actions.setDebouncedSearchTerm(searchTerm)
        },
        runNode: async ({ nodeId, direction }) => {
            const { upstream, downstream } = buildAdjacencyMaps(values.edges)
            const adjacency = direction === 'upstream' ? upstream : downstream
            const optimisticIds = traverseGraph(nodeId, adjacency)
            optimisticIds.add(nodeId)
            const now = Date.now()
            for (const id of optimisticIds) {
                if (!nodeStartTimes.has(id)) {
                    nodeStartTimes.set(id, now)
                }
            }
            actions.setRunningNodeIds(new Set([...values.runningNodeIds, ...optimisticIds]))

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
            actions.loadRecentJobs()
            try {
                const running = await api.dataModelingJobs.listRunning()
                actions.pollRunningJobsSuccess(running)
            } catch {
                // keep stale data during transient failures
            }
        },
        pollRunningJobsSuccess: ({ runningJobs }) => {
            const now = Date.now()
            const runningSavedQueryIds = new Set(runningJobs.map((job) => job.saved_query_id))
            const newRunningNodeIds = new Set<string>()

            for (const node of values.nodes) {
                if (node.data.savedQueryId && runningSavedQueryIds.has(node.data.savedQueryId)) {
                    newRunningNodeIds.add(node.id)
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
        loadRecentJobs: async () => {
            try {
                const recent = await api.dataModelingJobs.listRecent()
                actions.loadRecentJobsSuccess(recent)
            } catch {
                // silent failure
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
    })),
    afterMount(({ actions }) => {
        actions.loadDataModelingNodes()
        actions.loadDataModelingEdges()
        actions.loadRecentJobs()
        actions.startPollingRunningJobs()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPollingRunningJobs()
    }),
])
