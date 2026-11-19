import type { Edge, Node } from '@xyflow/react'

import type { DependencyEdgeApi, DependencyKindEnumApi } from './generated/api.schemas'
import { SERVICE_NODE_HEIGHT, SERVICE_NODE_WIDTH } from './serviceMap'

// The same threshold the map uses to draw a failing call.
export const FAILING_ERROR_RATE = 0.05
const MIN_EDGE_WIDTH = 1
const MAX_EDGE_WIDTH = 6

export const DEPENDENCY_KIND_LABEL: Record<DependencyKindEnumApi, string> = {
    service: 'Service',
    database: 'Database',
    queue: 'Queue',
    external: 'External',
}

export type DependencyNodeData = {
    name: string
    kind: DependencyKindEnumApi
    inferred: boolean
    requests: number
    errorRate: number
}

export type DependencyEdgeData = {
    requests: number
    errorRate: number
    width: number
}

export type DependencyMapNode = Node<DependencyNodeData, 'dependency'>
export type DependencyMapEdge = Edge<DependencyEdgeData>

export interface DependencyGraph {
    nodes: DependencyMapNode[]
    edges: DependencyMapEdge[]
}

export interface DependencySplit {
    upstream: DependencyEdgeApi[]
    downstream: DependencyEdgeApi[]
}

export function errorRateOf(edge: Pick<DependencyEdgeApi, 'requests' | 'error_count'>): number {
    return edge.requests > 0 ? edge.error_count / edge.requests : 0
}

export function edgesForService(edges: DependencyEdgeApi[], service: string | null): DependencyEdgeApi[] {
    return service ? edges.filter((edge) => edge.caller === service || edge.callee === service) : edges
}

export function splitDependencies(edges: DependencyEdgeApi[], service: string): DependencySplit {
    return {
        upstream: edges.filter((edge) => edge.callee === service && edge.caller !== service),
        downstream: edges.filter((edge) => edge.caller === service && edge.callee !== service),
    }
}

export function serviceNamesOf(edges: DependencyEdgeApi[]): string[] {
    const names = new Set<string>()
    for (const edge of edges) {
        names.add(edge.caller)
        if (!edge.inferred) {
            names.add(edge.callee)
        }
    }
    return [...names].sort()
}

export function buildDependencyGraph(edges: DependencyEdgeApi[]): DependencyGraph {
    const nodes = new Map<string, DependencyNodeData>()
    const incoming = new Map<string, { requests: number; errors: number }>()
    for (const edge of edges) {
        if (!nodes.has(edge.caller)) {
            nodes.set(edge.caller, { name: edge.caller, kind: 'service', inferred: false, requests: 0, errorRate: 0 })
        }
        const callee = nodes.get(edge.callee)
        if (!callee || (callee.inferred && !edge.inferred)) {
            nodes.set(edge.callee, {
                name: edge.callee,
                kind: edge.kind,
                inferred: edge.inferred,
                requests: 0,
                errorRate: 0,
            })
        }
        const total = incoming.get(edge.callee) ?? { requests: 0, errors: 0 }
        incoming.set(edge.callee, { requests: total.requests + edge.requests, errors: total.errors + edge.error_count })
    }
    // A name seen as a caller sends its own spans, so it is never drawn as inferred.
    for (const edge of edges) {
        const caller = nodes.get(edge.caller)
        if (caller?.inferred) {
            nodes.set(edge.caller, { ...caller, kind: 'service', inferred: false })
        }
    }
    const maxRequests = Math.max(1, ...edges.map((edge) => edge.requests))

    return {
        nodes: [...nodes.values()]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((data) => {
                const total = incoming.get(data.name)
                return {
                    id: data.name,
                    type: 'dependency' as const,
                    position: { x: 0, y: 0 },
                    width: SERVICE_NODE_WIDTH,
                    height: SERVICE_NODE_HEIGHT,
                    data: {
                        ...data,
                        requests: total?.requests ?? 0,
                        errorRate: total ? errorRateOf({ requests: total.requests, error_count: total.errors }) : 0,
                    },
                }
            }),
        edges: edges.map((edge) => ({
            id: `${edge.caller}->${edge.callee}`,
            source: edge.caller,
            target: edge.callee,
            data: {
                requests: edge.requests,
                errorRate: errorRateOf(edge),
                width: MIN_EDGE_WIDTH + ((MAX_EDGE_WIDTH - MIN_EDGE_WIDTH) * edge.requests) / maxRequests,
            },
        })),
    }
}
