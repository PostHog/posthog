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
        const upstreamNodes = upstream.get(edge.target_id)
        if (upstreamNodes) {
            upstreamNodes.push(edge.source_id)
        } else {
            upstream.set(edge.target_id, [edge.source_id])
        }

        const downstreamNodes = downstream.get(edge.source_id)
        if (downstreamNodes) {
            downstreamNodes.push(edge.target_id)
        } else {
            downstream.set(edge.source_id, [edge.target_id])
        }
    }

    return { upstream, downstream }
}

function walk(startId: string, adjacency: Map<string, string[]>, reached: Set<string>): void {
    const queue = [startId]
    for (let cursor = 0; cursor < queue.length; cursor++) {
        const current = queue[cursor]
        for (const neighbor of adjacency.get(current) ?? []) {
            if (!reached.has(neighbor)) {
                reached.add(neighbor)
                queue.push(neighbor)
            }
        }
    }
}

function walkDistances(startId: string, adjacency: Map<string, string[]>, distances: Map<string, number>): void {
    const queue = [startId]
    for (let cursor = 0; cursor < queue.length; cursor++) {
        const current = queue[cursor]
        const distance = distances.get(current) ?? 0
        for (const neighbor of adjacency.get(current) ?? []) {
            const nextDistance = distance + 1
            const knownDistance = distances.get(neighbor)
            if (knownDistance === undefined || nextDistance < knownDistance) {
                distances.set(neighbor, nextDistance)
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
    // Lowercase each name once. The comparator runs O(n log n) times, so lowercasing inside it
    // allocates two strings per comparison, and a plain search matches on every keystroke.
    const matches: { node: DataModelingNode; lowerName: string }[] = []
    for (const node of nodes) {
        const lowerName = node.name.toLowerCase()
        if (lowerName.includes(needle)) {
            matches.push({ node, lowerName })
        }
    }
    matches.sort((a, b) => {
        const exact = Number(b.lowerName === needle) - Number(a.lowerName === needle)
        return exact !== 0 ? exact : a.node.name.length - b.node.name.length
    })
    return matches.map((match) => match.node)
}

/**
 * The ordered nodes for a lineage selector, or null when the term is a plain name search.
 *
 * The anchor comes first. Related nodes follow by graph distance and then name. Upstream and
 * downstream walks stay separate, so a bidirectional selector does not reach sibling nodes.
 */
export function orderedNodesForLineageSearch(
    nodes: DataModelingNode[],
    edges: DataModelingEdge[],
    parsed: ParsedLineageSearch
): DataModelingNode[] | null {
    if (parsed.mode === 'search' || !parsed.term) {
        return null
    }
    const anchor = matchNodesByName(nodes, parsed.term)[0]
    if (!anchor) {
        return []
    }

    const maps = buildAdjacencyMaps(edges)
    const distances = new Map<string, number>([[anchor.id, 0]])
    if (parsed.mode === 'upstream' || parsed.mode === 'both') {
        walkDistances(anchor.id, maps.upstream, distances)
    }
    if (parsed.mode === 'downstream' || parsed.mode === 'both') {
        walkDistances(anchor.id, maps.downstream, distances)
    }

    return nodes
        .filter((node) => distances.has(node.id))
        .sort((a, b) => {
            const distanceDifference = (distances.get(a.id) ?? 0) - (distances.get(b.id) ?? 0)
            return distanceDifference || a.name.localeCompare(b.name)
        })
}

/** The node ids a lineage selector keeps, or null when a plain search does not prune the graph. */
export function nodeIdsForLineageSearch(
    nodes: DataModelingNode[],
    edges: DataModelingEdge[],
    parsed: ParsedLineageSearch
): Set<string> | null {
    const orderedNodes = orderedNodesForLineageSearch(nodes, edges, parsed)
    return orderedNodes === null ? null : new Set(orderedNodes.map((node) => node.id))
}

/** Keeps only edges whose endpoints both survived filtering, so no edge dangles. */
export function edgesWithinNodes(edges: DataModelingEdge[], nodeIds: Set<string>): DataModelingEdge[] {
    return edges.filter((edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id))
}
