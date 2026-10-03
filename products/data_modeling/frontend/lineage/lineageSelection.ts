import { DataModelingEdge } from '~/types'

import { buildAdjacencyMaps, traverseLineage } from './lineageSearch'

export type LineageSelectionMode = 'upstream' | 'downstream' | 'both'

export interface LineageSelection {
    nodeId: string
    mode: LineageSelectionMode
}

export interface LineageCone {
    nodeIds: Set<string>
    edgeIds: Set<string>
}

/**
 * The nodes and edges on a selected node's lineage.
 *
 * Edges are matched per direction. An edge from an upstream node straight to a downstream node has
 * both ends in the cone, but it does not pass through the selected node, so it is left out.
 */
export function lineageCone(edges: DataModelingEdge[], selection: LineageSelection): LineageCone {
    const maps = buildAdjacencyMaps(edges)
    const includeUpstream = selection.mode !== 'downstream'
    const includeDownstream = selection.mode !== 'upstream'
    const upstream = includeUpstream ? traverseLineage(selection.nodeId, maps, 'upstream') : new Set<string>()
    const downstream = includeDownstream ? traverseLineage(selection.nodeId, maps, 'downstream') : new Set<string>()

    const edgeIds = new Set<string>()
    for (const edge of edges) {
        const onUpstreamPath = upstream.has(edge.source_id) && upstream.has(edge.target_id)
        const onDownstreamPath = downstream.has(edge.source_id) && downstream.has(edge.target_id)
        if (onUpstreamPath || onDownstreamPath) {
            edgeIds.add(edge.id)
        }
    }

    return { nodeIds: new Set([selection.nodeId, ...upstream, ...downstream]), edgeIds }
}
