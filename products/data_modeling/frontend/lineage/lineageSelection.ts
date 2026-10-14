import { DataModelingEdge } from '~/types'

import { buildAdjacencyMaps, traverseLineage } from './lineageSearch'

export interface LineageCone {
    nodeIds: Set<string>
    edgeIds: Set<string>
}

/** The nodes and edges that pass through the selected node in either direction. */
export function lineageCone(edges: DataModelingEdge[], nodeId: string): LineageCone {
    const maps = buildAdjacencyMaps(edges)
    const upstream = traverseLineage(nodeId, maps, 'upstream')
    const downstream = traverseLineage(nodeId, maps, 'downstream')
    const edgeIds = new Set<string>()

    for (const edge of edges) {
        const onUpstreamPath = upstream.has(edge.source_id) && upstream.has(edge.target_id)
        const onDownstreamPath = downstream.has(edge.source_id) && downstream.has(edge.target_id)
        if (onUpstreamPath || onDownstreamPath) {
            edgeIds.add(edge.id)
        }
    }

    return { nodeIds: new Set([nodeId, ...upstream, ...downstream]), edgeIds }
}
