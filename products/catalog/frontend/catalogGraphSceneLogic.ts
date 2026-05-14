import { Edge, MarkerType, Node } from '@xyflow/react'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { catalogNodesGraphRetrieve } from 'products/catalog/frontend/generated/api'
import type {
    CatalogGraphDTOApi,
    CatalogNodeDTOApi,
    CatalogRelationshipDTOApi,
} from 'products/catalog/frontend/generated/api.schemas'

import type { catalogGraphSceneLogicType } from './catalogGraphSceneLogicType'
import { applyForceLayout } from './graphAutolayout'

export interface CatalogGraphNodeData extends Record<string, unknown> {
    node: CatalogNodeDTOApi
    domainColor: string
}

export interface CatalogGraphEdgeData extends Record<string, unknown> {
    relationship: CatalogRelationshipDTOApi
}

// Deterministic pastel-ish hue per business_domain. Hash → HSL.
function domainColor(domain: string | null | undefined): string {
    if (!domain) {
        return 'var(--border)'
    }
    let hash = 0
    for (let i = 0; i < domain.length; i++) {
        hash = (hash * 31 + domain.charCodeAt(i)) | 0
    }
    const hue = ((hash % 360) + 360) % 360
    return `hsl(${hue}, 60%, 55%)`
}

function buildReactFlowNodes(graph: CatalogGraphDTOApi): Node<CatalogGraphNodeData>[] {
    return graph.nodes.map((n) => ({
        id: n.id,
        type: 'catalogNode',
        position: { x: 0, y: 0 },
        data: { node: n, domainColor: domainColor(n.business_domain) },
    }))
}

function buildReactFlowEdges(graph: CatalogGraphDTOApi): Edge<CatalogGraphEdgeData>[] {
    return (
        graph.relationships
            // Hide rejected edges by default — toggle filter is v2.
            .filter((r) => r.status !== 'rejected')
            .map((r) => {
                // Literal hex colours instead of CSS variables: React Flow renders
                // edges inside an isolated SVG layer where var(--text-secondary)
                // doesn't resolve, so the stroke would come out empty.
                const stroke = r.status === 'stale' ? '#f59e0b' : '#71717a'
                return {
                    id: r.id,
                    source: r.source_node_id,
                    target: r.target_node_id,
                    data: { relationship: r },
                    animated: false,
                    markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
                    style: {
                        strokeWidth: 1.5,
                        opacity: 0.3 + 0.7 * Math.max(0, Math.min(1, r.confidence)),
                        strokeDasharray: r.status === 'proposed' ? '4 4' : undefined,
                        stroke,
                    },
                }
            })
    )
}

// Pick the source+target handle pair that minimises the angle the edge has to
// travel — for a force-directed layout this is what makes edges look sensible
// instead of always entering/exiting from the same side.
function pickHandles(
    source: Node<CatalogGraphNodeData>,
    target: Node<CatalogGraphNodeData>
): { sourceHandle: string; targetHandle: string } {
    const dx = target.position.x - source.position.x
    const dy = target.position.y - source.position.y
    if (Math.abs(dx) > Math.abs(dy)) {
        return dx > 0
            ? { sourceHandle: 's-right', targetHandle: 't-left' }
            : { sourceHandle: 's-left', targetHandle: 't-right' }
    }
    return dy > 0
        ? { sourceHandle: 's-bottom', targetHandle: 't-top' }
        : { sourceHandle: 's-top', targetHandle: 't-bottom' }
}

export const catalogGraphSceneLogic = kea<catalogGraphSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogGraphSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setNodes: (nodes: Node<CatalogGraphNodeData>[]) => ({ nodes }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        // Pushes an updated CatalogNodeDTO back into both the graph payload and the
        // React Flow node data so saves made via the side panel reflect on the canvas
        // (status badge, name, description, confidence dot) without a page refresh.
        replaceGraphNode: (node: CatalogNodeDTOApi) => ({ node }),
    }),

    loaders(({ values }) => ({
        graph: [
            null as CatalogGraphDTOApi | null,
            {
                loadGraph: async () => {
                    return await catalogNodesGraphRetrieve(String(values.currentProjectId))
                },
            },
        ],
    })),

    reducers({
        reactFlowNodes: [
            [] as Node<CatalogGraphNodeData>[],
            {
                setNodes: (_, { nodes }) => nodes,
                replaceGraphNode: (state, { node }) =>
                    state.map((n) =>
                        n.id === node.id
                            ? { ...n, data: { ...n.data, node, domainColor: domainColor(node.business_domain) } }
                            : n
                    ),
            },
        ],
        selectedNodeId: [
            null as string | null,
            {
                setSelectedNodeId: (_, { selectedNodeId }) => selectedNodeId,
            },
        ],
        graph: {
            replaceGraphNode: (state, { node }) =>
                state ? { ...state, nodes: state.nodes.map((n) => (n.id === node.id ? node : n)) } : state,
        },
    }),

    selectors({
        reactFlowEdges: [
            (s) => [s.graph, s.reactFlowNodes],
            (graph, nodes): Edge<CatalogGraphEdgeData>[] => {
                if (!graph) {
                    return []
                }
                const byId = new Map(nodes.map((n) => [n.id, n]))
                return buildReactFlowEdges(graph).map((e) => {
                    const src = byId.get(e.source)
                    const tgt = byId.get(e.target)
                    if (!src || !tgt) {
                        return e
                    }
                    return { ...e, ...pickHandles(src, tgt) }
                })
            },
        ],
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'catalog', name: 'Catalog' }]],
    }),

    listeners(({ actions }) => ({
        loadGraphSuccess: async ({ graph }) => {
            if (!graph) {
                actions.setNodes([])
                return
            }
            const initial = buildReactFlowNodes(graph)
            const edges = buildReactFlowEdges(graph)
            const laidOut = await applyForceLayout(initial, edges)
            actions.setNodes(laidOut)
        },
    })),

    urlToAction(({ actions }) => ({
        '/catalog/graph': () => {
            actions.loadGraph()
        },
    })),
])
