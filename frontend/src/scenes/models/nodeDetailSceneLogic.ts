import { MarkerType, Position } from '@xyflow/react'
import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, DataModelingEdge, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

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

function buildSubgraph(
    currentNodeId: string,
    allNodes: DataModelingNode[],
    allEdges: DataModelingEdge[]
): { nodeIds: Set<string>; edges: DataModelingEdge[] } {
    const edgesBySource = new Map<string, DataModelingEdge[]>()
    const edgesByTarget = new Map<string, DataModelingEdge[]>()
    for (const edge of allEdges) {
        if (!edgesBySource.has(edge.source_id)) {
            edgesBySource.set(edge.source_id, [])
        }
        edgesBySource.get(edge.source_id)!.push(edge)
        if (!edgesByTarget.has(edge.target_id)) {
            edgesByTarget.set(edge.target_id, [])
        }
        edgesByTarget.get(edge.target_id)!.push(edge)
    }

    // Traverse upstream (follow edges backward from current node)
    const nodeIds = new Set<string>([currentNodeId])
    const upstreamQueue = [currentNodeId]
    while (upstreamQueue.length > 0) {
        const id = upstreamQueue.shift()!
        for (const edge of edgesByTarget.get(id) ?? []) {
            if (!nodeIds.has(edge.source_id)) {
                nodeIds.add(edge.source_id)
                upstreamQueue.push(edge.source_id)
            }
        }
    }

    // Traverse downstream (follow edges forward from current node)
    const downstreamQueue = [currentNodeId]
    while (downstreamQueue.length > 0) {
        const id = downstreamQueue.shift()!
        for (const edge of edgesBySource.get(id) ?? []) {
            if (!nodeIds.has(edge.target_id)) {
                nodeIds.add(edge.target_id)
                downstreamQueue.push(edge.target_id)
            }
        }
    }

    const subgraphEdges = allEdges.filter((e) => nodeIds.has(e.source_id) && nodeIds.has(e.target_id))
    return { nodeIds, edges: subgraphEdges }
}

function toReactFlowGraph(
    currentNodeId: string,
    allNodes: DataModelingNode[],
    allEdges: DataModelingEdge[]
): { nodes: Node[]; edges: Edge[] } {
    const { nodeIds, edges: subgraphEdges } = buildSubgraph(currentNodeId, allNodes, allEdges)
    const subgraphNodes = allNodes.filter((n) => nodeIds.has(n.id))

    const nodes: Node[] = subgraphNodes.map((node) => {
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

    const edges: Edge[] = subgraphEdges.map((edge) => ({
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
                    const [nodesResponse, edgesResponse] = await Promise.all([
                        api.dataModelingNodes.list(),
                        api.dataModelingEdges.list(),
                    ])
                    const { nodes, edges } = toReactFlowGraph(props.id, nodesResponse.results, edgesResponse.results)
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
    })),
    actions({
        openQueryModal: true,
        closeQueryModal: true,
        openLineageModal: true,
        closeLineageModal: true,
        updateNodeDescription: (description: string) => ({ description }),
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
    }),
    selectors({
        nodeType: [(s) => [s.node], (node: DataModelingNode | null) => node?.type ?? null],
        breadcrumbs: [
            (s) => [s.node],
            (node: DataModelingNode | null): Breadcrumb[] => [
                {
                    key: Scene.Models,
                    name: 'Models',
            actions.loadLineageGraph()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNode()
    }),
    beforeUnmount(({ actions }) => {
        actions.closeQueryModal()
        actions.closeLineageModal()
    }),
])
