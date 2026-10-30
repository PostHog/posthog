import type { Edge, Node } from '@xyflow/react'
import type { ElkNode } from 'elkjs'

import { getElk } from 'lib/elk'

import type { ServiceEdgeApi, ServiceHealthApi } from './generated/api.schemas'

export const SERVICE_NODE_WIDTH = 200
export const SERVICE_NODE_HEIGHT = 64
const MIN_EDGE_WIDTH = 1
const MAX_EDGE_WIDTH = 6

export type ServiceNodeData = {
    name: string
    service: ServiceHealthApi | null
}

export type ServiceEdgeData = {
    calls: number
    errorRate: number
    p95Ms: number | null
    width: number
}

export type ServiceMapNode = Node<ServiceNodeData, 'service'>
export type ServiceMapEdge = Edge<ServiceEdgeData>

export interface ServiceGraph {
    nodes: ServiceMapNode[]
    edges: ServiceMapEdge[]
}

export function buildServiceGraph(services: ServiceHealthApi[], edges: ServiceEdgeApi[]): ServiceGraph {
    const health = new Map(services.map((row) => [row.service_name, row]))
    const names = new Set(services.map((row) => row.service_name))
    for (const edge of edges) {
        names.add(edge.caller)
        names.add(edge.callee)
    }
    const maxCalls = Math.max(1, ...edges.map((edge) => edge.calls))

    return {
        nodes: [...names].sort().map((name) => ({
            id: name,
            type: 'service',
            position: { x: 0, y: 0 },
            width: SERVICE_NODE_WIDTH,
            height: SERVICE_NODE_HEIGHT,
            data: { name, service: health.get(name) ?? null },
        })),
        edges: edges.map((edge) => ({
            id: `${edge.caller}->${edge.callee}`,
            source: edge.caller,
            target: edge.callee,
            data: {
                calls: edge.calls,
                errorRate: edge.calls > 0 ? edge.error_count / edge.calls : 0,
                p95Ms: edge.p95_ms,
                width: MIN_EDGE_WIDTH + ((MAX_EDGE_WIDTH - MIN_EDGE_WIDTH) * edge.calls) / maxCalls,
            },
        })),
    }
}

export async function layoutServiceGraph(graph: ServiceGraph): Promise<ServiceGraph> {
    if (graph.nodes.length === 0) {
        return graph
    }
    const elk = await getElk()
    const laidOut: ElkNode = await elk.layout({
        id: 'root',
        layoutOptions: {
            'elk.algorithm': 'layered',
            'elk.direction': 'RIGHT',
            'elk.layered.spacing.nodeNodeBetweenLayers': '80',
            'elk.spacing.nodeNode': '24',
            'elk.separateConnectedComponents': 'true',
        },
        children: graph.nodes.map((node) => ({ id: node.id, width: SERVICE_NODE_WIDTH, height: SERVICE_NODE_HEIGHT })),
        edges: graph.edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
    })
    const positions = new Map((laidOut.children ?? []).map((child) => [child.id, { x: child.x ?? 0, y: child.y ?? 0 }]))
    return {
        nodes: graph.nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })),
        edges: graph.edges,
    }
}
