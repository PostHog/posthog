import { DataModelingEdge, DataModelingNode } from '~/types'

export type LineageSearchMode = 'search' | 'upstream' | 'downstream' | 'both'

export interface ParsedLineageSearch {
    mode: LineageSearchMode
    /** The name to anchor lineage traversal on, or the term to match for plain search */
    term: string
}

/**
 * dbt-style selectors: `+model` walks upstream, `model+` downstream, `+model+` both.
 * A bare term is a plain name match, which highlights rather than filters.
 */
export function parseLineageSearch(rawTerm: string): ParsedLineageSearch {
    const trimmed = rawTerm.trim()
    const leading = trimmed.startsWith('+')
    const trailing = trimmed.endsWith('+') && trimmed.length > 1
    const term = trimmed.slice(leading ? 1 : 0, trailing ? -1 : undefined).trim()

    if (leading && trailing) {
        return { mode: 'both', term }
    }
    if (leading) {
        return { mode: 'upstream', term }
    }
    if (trailing) {
        return { mode: 'downstream', term }
    }
    return { mode: 'search', term }
}

export interface AdjacencyMaps {
    upstream: Map<string, string[]>
    downstream: Map<string, string[]>
}

export function buildAdjacencyMaps(edges: DataModelingEdge[]): AdjacencyMaps {
    const upstream = new Map<string, string[]>()
    const downstream = new Map<string, string[]>()

    for (const edge of edges) {
        upstream.set(edge.target_id, [...(upstream.get(edge.target_id) ?? []), edge.source_id])
        downstream.set(edge.source_id, [...(downstream.get(edge.source_id) ?? []), edge.target_id])
    }

    return { upstream, downstream }
}

function walk(startId: string, adjacency: Map<string, string[]>, reached: Set<string>): void {
    const queue = [startId]
    while (queue.length > 0) {
        const current = queue.shift() as string
        for (const neighbor of adjacency.get(current) ?? []) {
            if (!reached.has(neighbor)) {
                reached.add(neighbor)
                queue.push(neighbor)
            }
        }
    }
}

/**
 * The nodes a selector reaches from an anchor.
 *
 * `both` unions two one-way walks rather than walking both ways at each hop. Alternating direction
 * would reach siblings through a shared parent, which is the whole connected component, not lineage.
 */
export function traverseLineage(startId: string, maps: AdjacencyMaps, mode: LineageSearchMode): Set<string> {
    const reached = new Set<string>([startId])
    if (mode === 'upstream' || mode === 'both') {
        walk(startId, maps.upstream, reached)
    }
    if (mode === 'downstream' || mode === 'both') {
        walk(startId, maps.downstream, reached)
    }
    return reached
}

/** Nodes whose name contains the term, best match first so lineage anchors on the closest name. */
export function matchNodesByName(nodes: DataModelingNode[], term: string): DataModelingNode[] {
    const needle = term.toLowerCase()
    if (!needle) {
        return []
    }
    return nodes
        .filter((node) => node.name.toLowerCase().includes(needle))
        .sort((a, b) => {
            const exact = Number(b.name.toLowerCase() === needle) - Number(a.name.toLowerCase() === needle)
            return exact !== 0 ? exact : a.name.length - b.name.length
        })
}

/** Keeps only edges whose endpoints both survived filtering, so no edge dangles. */
export function edgesWithinNodes(edges: DataModelingEdge[], nodeIds: Set<string>): DataModelingEdge[] {
    return edges.filter((edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id))
}
