import { MarkerType, Position } from '@xyflow/react'
import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { PaginatedResponse } from 'lib/api'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    Breadcrumb,
    DataModelingEdge,
    DataModelingJob,
    DataModelingJobStatus,
    DataModelingNode,
    DataWarehouseSavedQuery,
} from '~/types'

import { getFormattedNodes } from '../data-warehouse/scene/modeling/autolayout'
import { Edge, Node, NodeHandle } from '../data-warehouse/scene/modeling/types'
import type { nodeDetailSceneLogicType } from './nodeDetailSceneLogicType'

export interface NodeDetailSceneLogicProps {
    id: string
}

export interface LineageGraph {
    nodes: Node[]
    edges: Edge[]
}

export interface LineageGraphPair {
    compact: LineageGraph
    full: LineageGraph
}

const COMPACT_NODE_WIDTH = 180
const COMPACT_NODE_HEIGHT = 44

function toReactFlowGraph(
    apiNodes: DataModelingNode[],
    apiEdges: DataModelingEdge[]
): { nodes: Node[]; edges: Edge[] } {
    const nodes: Node[] = apiNodes.map((node) => {
        const handles: NodeHandle[] = [
            { id: `target_${node.id}`, type: 'target', position: Position.Left },
            { id: `source_${node.id}`, type: 'source', position: Position.Right },
        ]
        return {
            id: node.id,
            type: 'model',
            data: {
                id: node.id,
                name: node.name,
                type: node.type,
                dagId: node.dag_id,
                savedQueryId: node.saved_query_id,
                handles,
                upstreamCount: node.upstream_count,
                downstreamCount: node.downstream_count,
                isRunning: false,
                isTypeHighlighted: false,
                userTag: node.user_tag,
                lastJobStatus: node.last_run_status,
                lastRunAt: node.last_run_at,
                syncInterval: node.sync_interval,
            },
            position: { x: 0, y: 0 },
            deletable: false,
            selectable: false,
            draggable: false,
            connectable: false,
        }
    })

    const edges: Edge[] = apiEdges.map((edge) => ({
        id: `${edge.source_id}->${edge.target_id}`,
        source: edge.source_id,
        target: edge.target_id,
        type: 'straight',
        deletable: false,
        markerEnd: { type: MarkerType.ArrowClosed },
        sourceHandle: `source_${edge.source_id}`,
        targetHandle: `target_${edge.target_id}`,
    }))

    return { nodes, edges }
}

export const nodeDetailSceneLogic = kea<nodeDetailSceneLogicType>([
    props({} as NodeDetailSceneLogicProps),
    path(['scenes', 'models', 'nodeDetailSceneLogic']),
    key((props: NodeDetailSceneLogicProps) => props.id),
    connect({
        actions: [dataWarehouseViewsLogic, ['updateDataWarehouseSavedQuerySuccess']],
    }),
    loaders(({ props }) => ({
        node: [
            null as DataModelingNode | null,
            {
                loadNode: async () => {
                    return await api.dataModelingNodes.get(props.id)
                },
            },
        ],
        savedQuery: [
            null as DataWarehouseSavedQuery | null,
            {
                loadSavedQuery: async (savedQueryId: string) => {
                    return await api.dataWarehouseSavedQueries.get(savedQueryId)
                },
            },
        ],
        lineageGraph: [
            null as LineageGraphPair | null,
            {
                loadLineageGraph: async () => {
                    const response = await api.dataModelingNodes.lineage(props.id)
                    const { nodes, edges } = toReactFlowGraph(response.nodes, response.edges)
                    if (nodes.length === 0) {
                        return { compact: { nodes: [], edges: [] }, full: { nodes: [], edges: [] } }
                    }
                    const [compactNodes, fullNodes] = await Promise.all([
                        getFormattedNodes(nodes, edges, 'RIGHT', COMPACT_NODE_WIDTH, COMPACT_NODE_HEIGHT),
                        getFormattedNodes(nodes, edges, 'RIGHT'),
                    ])
                    return {
                        compact: { nodes: compactNodes, edges },
                        full: { nodes: fullNodes, edges },
                    }
                },
            },
        ],
        materializationJobs: [
            null as PaginatedResponse<DataModelingJob> | null,
            {
                loadMaterializationJobs: async (savedQueryId: string) => {
                    return await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(savedQueryId, 10, 0)
                },
                loadMaterializationJobsFromUrl: async (url: string) => {
                    return await api.get(url)
                },
            },
        ],
    })),
    actions({
        openQueryModal: true,
        closeQueryModal: true,
        openLineageModal: true,
        closeLineageModal: true,
        loadNextJobs: true,
        loadPreviousJobs: true,
        updateNodeDescription: (description: string) => ({ description }),
        loadRecentJobs: true,
        loadRecentJobsSuccess: (recentJobs: DataModelingJob[]) => ({ recentJobs }),
        setFromNode: (fromNodeId: string | null, fromNodeName: string | null) => ({ fromNodeId, fromNodeName }),
    }),
    reducers({
        queryModalOpen: [
            false,
            {
                openQueryModal: () => true,
                closeQueryModal: () => false,
                loadNode: () => false,
            },
        ],
        lineageModalOpen: [
            false,
            {
                openLineageModal: () => true,
                closeLineageModal: () => false,
                loadNode: () => false,
            },
        ],
        fromNodeId: [
            null as string | null,
            {
                setFromNode: (_, { fromNodeId }) => fromNodeId,
            },
        ],
        fromNodeName: [
            null as string | null,
            {
                setFromNode: (_, { fromNodeName }) => fromNodeName,
            },
        ],
        latestJobMetadataBySavedQueryId: [
            {} as Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }>,
            {
                loadRecentJobsSuccess: (_, { recentJobs }) => {
                    const map: Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }> = {}
                    for (const job of recentJobs) {
                        if (job.saved_query_id) {
                            map[job.saved_query_id] = {
                                status: job.status,
                                lastRunAt: job.last_run_at,
                            }
                        }
                    }
                    return map
                },
            },
        ],
    }),
    selectors({
        nodeType: [(s) => [s.node], (node: DataModelingNode | null) => node?.type ?? null],
        breadcrumbs: [
            (s) => [s.node, s.fromNodeId, s.fromNodeName],
            (node: DataModelingNode | null, fromNodeId: string | null, fromNodeName: string | null): Breadcrumb[] => {
                const crumbs: Breadcrumb[] = [
                    {
                        key: Scene.Models,
                        name: 'Models',
                        path: urls.models(),
                    },
                ]
                if (fromNodeId) {
                    crumbs.push({
                        key: [Scene.NodeDetail, fromNodeId],
                        name: fromNodeName || 'Node',
                        path: urls.nodeDetail(fromNodeId),
                    })
                }
                crumbs.push({
                    key: [Scene.NodeDetail, node?.id || 'loading'],
                    name: node?.name || 'Loading...',
                })
                return crumbs
            },
        ],
        latestRowCount: [
            (s) => [s.materializationJobs],
            (jobs: PaginatedResponse<DataModelingJob> | null): number | null => {
                const completed = jobs?.results?.find((j) => j.status === 'Completed')
                return completed?.rows_materialized ?? null
            },
        ],
        latestJobStatus: [
            (s) => [s.materializationJobs],
            (jobs: PaginatedResponse<DataModelingJob> | null): string | null => {
                const latest = jobs?.results?.[0]
                return latest?.status ?? null
            },
        ],
        latestJobMetadataByNodeId: [
            (s) => [s.lineageGraph, s.latestJobMetadataBySavedQueryId],
            (
                lineageGraph,
                latestJobMetadataBySavedQueryId
            ): Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }> => {
                const map: Record<string, { status: DataModelingJobStatus; lastRunAt: string | null }> = {}
                const nodes = lineageGraph?.compact?.nodes ?? []
                for (const node of nodes) {
                    if (node.data.savedQueryId && latestJobMetadataBySavedQueryId[node.data.savedQueryId]) {
                        map[node.id] = latestJobMetadataBySavedQueryId[node.data.savedQueryId]
                    }
                }
                return map
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        updateNodeDescription: async ({ description }) => {
            await api.dataModelingNodes.update(props.id, { description })
        },
        loadNodeSuccess: ({ node }) => {
            if (node?.saved_query_id) {
                actions.loadSavedQuery(node.saved_query_id)
            }
            actions.loadLineageGraph()
        },
        loadSavedQuerySuccess: ({ savedQuery }) => {
            if (savedQuery?.is_materialized) {
                actions.loadMaterializationJobs(savedQuery.id)
            }
        },
        loadLineageGraphSuccess: () => {
            actions.loadRecentJobs()
        },
        loadRecentJobs: async () => {
            try {
                const recent = await api.dataModelingJobs.listRecent()
                actions.loadRecentJobsSuccess(recent)
            } catch {
                // silent failure
            }
        },
        updateDataWarehouseSavedQuerySuccess: ({ payload: updatePayload }) => {
            if (updatePayload?.id && updatePayload.id === values.savedQuery?.id) {
                actions.loadSavedQuery(updatePayload.id)
            }
        },
        loadNextJobs: () => {
            const nextUrl = values.materializationJobs?.next
            if (nextUrl) {
                actions.loadMaterializationJobsFromUrl(nextUrl)
            }
        },
        loadPreviousJobs: () => {
            const previousUrl = values.materializationJobs?.previous
            if (previousUrl) {
                actions.loadMaterializationJobsFromUrl(previousUrl)
            }
        },
    })),
    afterMount(({ actions }) => {
        const { searchParams } = router.values
        actions.setFromNode(searchParams.from_node ?? null, searchParams.from_node_name ?? null)
        actions.loadNode()
    }),
    beforeUnmount(({ actions }) => {
        actions.closeQueryModal()
        actions.closeLineageModal()
    }),
])
