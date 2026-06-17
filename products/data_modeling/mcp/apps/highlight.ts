// Pure upstream/downstream BFS over the edge list. Ported from the adjacency +
// traverseGraph helpers in
// frontend/src/scenes/data-warehouse/scene/dataModelingLogic.ts (kea coupling removed).

import type { DataModelEdge, NodeRole } from './types'

interface AdjacencyMaps {
    upstream: Map<string, string[]> // target -> sources
    downstream: Map<string, string[]> // source -> targets
}

export function buildAdjacencyMaps(edges: DataModelEdge[]): AdjacencyMaps {
    const upstream = new Map<string, string[]>()
    const downstream = new Map<string, string[]>()
    for (const edge of edges) {
        if (!upstream.has(edge.target_id)) {
            upstream.set(edge.target_id, [])
        }
        upstream.get(edge.target_id)!.push(edge.source_id)
        if (!downstream.has(edge.source_id)) {
            downstream.set(edge.source_id, [])
        }
        downstream.get(edge.source_id)!.push(edge.target_id)
    }
    return { upstream, downstream }
}

function traverse(startId: string, adjacency: Map<string, string[]>): Set<string> {
    const result = new Set<string>()
    const queue = [startId]
    while (queue.length > 0) {
        const current = queue.shift()!
        for (const neighbor of adjacency.get(current) ?? []) {
            if (!result.has(neighbor)) {
                result.add(neighbor)
                queue.push(neighbor)
            }
        }
    }
    return result
}

export interface Lineage {
    upstreamIds: Set<string>
    downstreamIds: Set<string>
    roleOf: (nodeId: string) => NodeRole
}

/** Compute upstream/downstream reachable sets for a focal node, plus a role lookup. */
export function computeLineage(edges: DataModelEdge[], focalId: string | null): Lineage {
    const { upstream, downstream } = buildAdjacencyMaps(edges)
    const upstreamIds = focalId ? traverse(focalId, upstream) : new Set<string>()
    const downstreamIds = focalId ? traverse(focalId, downstream) : new Set<string>()

    const roleOf = (nodeId: string): NodeRole => {
        if (!focalId) {
            return 'other'
        }
        if (nodeId === focalId) {
            return 'focal'
        }
        if (upstreamIds.has(nodeId)) {
            return 'upstream'
        }
        if (downstreamIds.has(nodeId)) {
            return 'downstream'
        }
        return 'other'
    }

    return { upstreamIds, downstreamIds, roleOf }
}
