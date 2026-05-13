import { Edge, MarkerType, Node } from '@xyflow/react'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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
            .map((r) => ({
                id: r.id,
                source: r.source_node_id,
                target: r.target_node_id,
                data: { relationship: r },
                animated: false,
                markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--text-secondary)' },
                style: {
                    strokeWidth: 1.5,
                    opacity: 0.3 + 0.7 * Math.max(0, Math.min(1, r.confidence)),
                    strokeDasharray: r.status === 'proposed' ? '4 4' : undefined,
                    stroke: r.status === 'stale' ? 'var(--warning)' : 'var(--text-secondary)',
                },
            }))
    )
}

export const catalogGraphSceneLogic = kea<catalogGraphSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogGraphSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setNodes: (nodes: Node<CatalogGraphNodeData>[]) => ({ nodes }),
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
            },
        ],
    }),

    selectors({
        reactFlowEdges: [
            (s) => [s.graph],
            (graph): Edge<CatalogGraphEdgeData>[] => (graph ? buildReactFlowEdges(graph) : []),
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                { key: 'catalog', name: 'Catalog', path: urls.catalog() },
                { key: 'graph', name: 'Graph' },
            ],
        ],
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
