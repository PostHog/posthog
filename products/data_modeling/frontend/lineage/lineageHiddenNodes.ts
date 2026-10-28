import { DataModelingEdge } from '~/types'

import { buildAdjacencyMaps, edgesWithinNodes } from './lineageSearch'

export interface LineageEdge extends DataModelingEdge {
    throughHiddenNodes?: boolean
}

export interface HiddenNodeBridging {
    edges: LineageEdge[]
    hiddenDownstreamCounts: Map<string, number>
}

interface NodesReachedThroughHidden {
    hidden: Set<string>
    visible: Set<string>
}

function walkThroughHidden(
    startIds: Iterable<string>,
    adjacency: Map<string, string[]>,
    visibleNodeIds: Set<string>
): NodesReachedThroughHidden {
    const hidden = new Set<string>()
    const visible = new Set<string>()
    const queue = [...startIds]
    for (let cursor = 0; cursor < queue.length; cursor++) {
        for (const neighborId of adjacency.get(queue[cursor]) ?? []) {
            if (visibleNodeIds.has(neighborId)) {
                visible.add(neighborId)
            } else if (!hidden.has(neighborId)) {
                hidden.add(neighborId)
                queue.push(neighborId)
            }
        }
    }
    return { hidden, visible }
}

const edgeKey = (sourceId: string, targetId: string): string => `${sourceId}>${targetId}`

export function bridgeHiddenNodes(
    edges: DataModelingEdge[],
    scopeNodeIds: Set<string>,
    visibleNodeIds: Set<string>
): HiddenNodeBridging {
    const visibleEdges = edgesWithinNodes(edges, visibleNodeIds)
    if (scopeNodeIds.size === visibleNodeIds.size) {
        return { edges: visibleEdges, hiddenDownstreamCounts: new Map() }
    }

    const { upstream, downstream } = buildAdjacencyMaps(edgesWithinNodes(edges, scopeNodeIds))
    const hiddenLeadingToVisible = walkThroughHidden(visibleNodeIds, upstream, visibleNodeIds).hidden
    const realEdgeKeys = new Set(visibleEdges.map((edge) => edgeKey(edge.source_id, edge.target_id)))
    const bridgedEdges: LineageEdge[] = []
    const hiddenDownstreamCounts = new Map<string, number>()

    for (const sourceId of visibleNodeIds) {
        const reached = walkThroughHidden([sourceId], downstream, visibleNodeIds)
        for (const targetId of reached.visible) {
            if (!realEdgeKeys.has(edgeKey(sourceId, targetId))) {
                bridgedEdges.push({
                    id: `hidden:${sourceId}:${targetId}`,
                    source_id: sourceId,
                    target_id: targetId,
                    throughHiddenNodes: true,
                })
            }
        }
        const deadEndCount = [...reached.hidden].filter((nodeId) => !hiddenLeadingToVisible.has(nodeId)).length
        if (deadEndCount > 0) {
            hiddenDownstreamCounts.set(sourceId, deadEndCount)
        }
    }

    return { edges: [...visibleEdges, ...bridgedEdges], hiddenDownstreamCounts }
}
