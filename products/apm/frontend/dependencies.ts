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

export type ExternalHostGroup = {
    caller: string
    hostCount: number
    // The slowest host's p95, so an upper bound for the group rather than its real p95.
    p95MaxMs: number | null
}

export type DependencyNodeData = {
    name: string
    kind: DependencyKindEnumApi
    inferred: boolean
    requests: number
    errorRate: number
    group: ExternalHostGroup | null
}

export type DrawnDependencyEdge = DependencyEdgeApi & { group?: ExternalHostGroup }

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

export const DRAWN_EDGE_CAP = 40
export const MAX_UNGROUPED_EXTERNAL_HOSTS = 5

export function groupExternalHosts(edges: DependencyEdgeApi[]): DrawnDependencyEdge[] {
    const hostsByCaller = new Map<string, DependencyEdgeApi[]>()
    for (const edge of edges) {
        if (edge.kind === 'external') {
            hostsByCaller.set(edge.caller, [...(hostsByCaller.get(edge.caller) ?? []), edge])
        }
    }
    const grouped = [...hostsByCaller].filter(([, hosts]) => hosts.length > MAX_UNGROUPED_EXTERNAL_HOSTS)
    if (grouped.length === 0) {
        return edges
    }
    const groupedCallers = new Set(grouped.map(([caller]) => caller))
    const kept: DrawnDependencyEdge[] = edges.filter(
        (edge) => edge.kind !== 'external' || !groupedCallers.has(edge.caller)
    )
    for (const [caller, hosts] of grouped) {
        const p95s = hosts.map((host) => host.p95_ms).filter((ms): ms is number => ms !== null)
        const group = { caller, hostCount: hosts.length, p95MaxMs: p95s.length > 0 ? Math.max(...p95s) : null }
        kept.push({
            caller,
            callee: `external hosts called by ${caller}`,
            inferred: true,
            kind: 'external',
            requests: hosts.reduce((sum, host) => sum + host.requests, 0),
            error_count: hosts.reduce((sum, host) => sum + host.error_count, 0),
            p95_ms: group.p95MaxMs,
            group,
        })
    }
    return kept
}

export function drawableEdges(edges: DependencyEdgeApi[], service: string | null): DrawnDependencyEdge[] {
    return service ? edgesForService(edges, service) : groupExternalHosts(edges)
}

export function edgesToDraw(
    edges: DependencyEdgeApi[],
    service: string | null,
    showAll: boolean
): DrawnDependencyEdge[] {
    const drawable = drawableEdges(edges, service)
    if (service || showAll || drawable.length <= DRAWN_EDGE_CAP) {
        return drawable
    }
    return [...drawable].sort((a, b) => b.requests - a.requests).slice(0, DRAWN_EDGE_CAP)
}

// Changes only when the drawn nodes or edges change, so the map fits again then but keeps the zoom on a refresh.
export function graphKey(graph: DependencyGraph): string {
    const nodeIds = graph.nodes.map((node) => node.id).sort()
    const edgeIds = graph.edges.map((edge) => edge.id).sort()
    return [...nodeIds, ...edgeIds].join('\n')
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

export function buildDependencyGraph(edges: DrawnDependencyEdge[]): DependencyGraph {
    const nodes = new Map<string, DependencyNodeData>()
    const incoming = new Map<string, { requests: number; errors: number }>()
    for (const edge of edges) {
        if (!nodes.has(edge.caller)) {
            nodes.set(edge.caller, {
                name: edge.caller,
                kind: 'service',
                inferred: false,
                requests: 0,
                errorRate: 0,
                group: null,
            })
        }
        const callee = nodes.get(edge.callee)
        if (!callee || (callee.inferred && !edge.inferred)) {
            nodes.set(edge.callee, {
                name: edge.callee,
                kind: edge.kind,
                inferred: edge.inferred,
                requests: 0,
                errorRate: 0,
                group: edge.group ?? null,
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
