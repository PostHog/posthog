import { DataModelingEdge, DataModelingNode } from '~/types'

import { AdjacencyMaps, buildAdjacencyMaps, edgesWithinNodes } from './lineageSearch'

const PATH_COUNT_CEILING = 1_000_000
const CACHED_REACH_LIMIT = 2
const EMPTY_NODE_IDS: ReadonlySet<string> = new Set()

export interface LineageEdge extends DataModelingEdge {
    throughHiddenNodes?: boolean
}

export interface LineageGraphNode extends DataModelingNode {
    collapsed?: boolean
}

export interface HiddenNodeBridging {
    edges: LineageEdge[]
    hubNodeIds: Set<string>
}

function childrenFirstOrder(
    nodeIds: Iterable<string>,
    adjacency: Map<string, string[]>,
    include: (nodeId: string) => boolean
): string[] {
    const order: string[] = []
    const visited = new Set<string>()
    for (const startId of nodeIds) {
        if (!include(startId) || visited.has(startId)) {
            continue
        }
        visited.add(startId)
        const stack = [{ nodeId: startId, nextChild: 0 }]
        while (stack.length > 0) {
            const frame = stack[stack.length - 1]
            const children = adjacency.get(frame.nodeId) ?? []
            if (frame.nextChild === children.length) {
                order.push(frame.nodeId)
                stack.pop()
                continue
            }
            const childId = children[frame.nextChild++]
            if (include(childId) && !visited.has(childId)) {
                visited.add(childId)
                stack.push({ nodeId: childId, nextChild: 0 })
            }
        }
    }
    return order
}

class HiddenSubgraph {
    readonly terminals: Set<string>
    readonly hubNodeIds: Set<string>
    private readonly maps: AdjacencyMaps
    private readonly downstreamPaths: Map<string, number>
    private readonly cachedReach = new Map<string, ReadonlySet<string>>()

    constructor(
        scopedEdges: DataModelingEdge[],
        private readonly scopeNodeIds: Set<string>,
        private readonly visibleNodeIds: Set<string>
    ) {
        this.maps = buildAdjacencyMaps(scopedEdges)
        this.downstreamPaths = this.countVisiblePaths(this.maps.downstream)
        this.hubNodeIds = this.findHubs(this.countVisiblePaths(this.maps.upstream))
        this.terminals = new Set([...visibleNodeIds, ...this.hubNodeIds])
        this.walkHiddenNodes()
    }

    terminalsReachedFrom(sourceId: string): Set<string> {
        const reached = new Set<string>()
        const visited = new Set<string>()
        const stack = this.hiddenChildren(sourceId)
        while (stack.length > 0) {
            const nodeId = stack.pop() as string
            if (visited.has(nodeId)) {
                continue
            }
            visited.add(nodeId)
            const cached = this.cachedReach.get(nodeId)
            if (cached) {
                cached.forEach((targetId) => reached.add(targetId))
                continue
            }
            for (const childId of this.maps.downstream.get(nodeId) ?? []) {
                if (this.terminals.has(childId)) {
                    reached.add(childId)
                } else {
                    stack.push(childId)
                }
            }
        }
        reached.delete(sourceId)
        return reached
    }

    private isHidden = (nodeId: string): boolean => !this.visibleNodeIds.has(nodeId)

    private isHiddenNonTerminal = (nodeId: string): boolean => !this.terminals.has(nodeId)

    private hiddenChildren(nodeId: string): string[] {
        return (this.maps.downstream.get(nodeId) ?? []).filter(this.isHiddenNonTerminal)
    }

    private findHubs(upstreamPaths: Map<string, number>): Set<string> {
        return new Set(
            [...upstreamPaths.keys()].filter((nodeId) => {
                const upstream = upstreamPaths.get(nodeId) ?? 0
                const downstream = this.downstreamPaths.get(nodeId) ?? 0
                return upstream * downstream > upstream + downstream
            })
        )
    }

    private countVisiblePaths(adjacency: Map<string, string[]>): Map<string, number> {
        const counts = new Map<string, number>()
        for (const nodeId of childrenFirstOrder(this.scopeNodeIds, adjacency, this.isHidden)) {
            let total = 0
            for (const neighborId of adjacency.get(nodeId) ?? []) {
                total += this.isHidden(neighborId) ? (counts.get(neighborId) ?? 0) : 1
            }
            counts.set(nodeId, Math.min(total, PATH_COUNT_CEILING))
        }
        return counts
    }

    private walkHiddenNodes(): void {
        for (const nodeId of childrenFirstOrder(this.scopeNodeIds, this.maps.downstream, this.isHiddenNonTerminal)) {
            if ((this.downstreamPaths.get(nodeId) ?? 0) <= CACHED_REACH_LIMIT) {
                this.cachedReach.set(nodeId, this.reachFromCachedChildren(nodeId))
            }
        }
    }

    private reachFromCachedChildren(nodeId: string): ReadonlySet<string> {
        const reached = new Set<string>()
        for (const childId of this.maps.downstream.get(nodeId) ?? []) {
            if (this.terminals.has(childId)) {
                reached.add(childId)
            } else {
                this.cachedReach.get(childId)?.forEach((targetId) => reached.add(targetId))
            }
        }
        return reached.size === 0 ? EMPTY_NODE_IDS : reached
    }
}

export function nodesWithHubs(
    scopedNodes: DataModelingNode[],
    visibleNodeIds: Set<string>,
    hubNodeIds: Set<string>
): LineageGraphNode[] {
    return scopedNodes
        .filter((node) => visibleNodeIds.has(node.id) || hubNodeIds.has(node.id))
        .map((node) => (hubNodeIds.has(node.id) ? { ...node, collapsed: true } : node))
}

const edgeKey = (sourceId: string, targetId: string): string => `${sourceId}>${targetId}`

export function bridgeHiddenNodes(
    edges: DataModelingEdge[],
    scopeNodeIds: Set<string>,
    visibleNodeIds: Set<string>
): HiddenNodeBridging {
    if (scopeNodeIds.size === visibleNodeIds.size) {
        return {
            edges: edgesWithinNodes(edges, visibleNodeIds),
            hubNodeIds: new Set(),
        }
    }

    const subgraph = new HiddenSubgraph(edgesWithinNodes(edges, scopeNodeIds), scopeNodeIds, visibleNodeIds)
    const realEdges = edgesWithinNodes(edges, subgraph.terminals)
    const realEdgeKeys = new Set(realEdges.map((edge) => edgeKey(edge.source_id, edge.target_id)))
    const bridgedEdges: LineageEdge[] = []

    for (const sourceId of subgraph.terminals) {
        for (const targetId of subgraph.terminalsReachedFrom(sourceId)) {
            if (!realEdgeKeys.has(edgeKey(sourceId, targetId))) {
                bridgedEdges.push({
                    id: `hidden:${sourceId}:${targetId}`,
                    source_id: sourceId,
                    target_id: targetId,
                    throughHiddenNodes: true,
                })
            }
        }
    }

    return { edges: [...realEdges, ...bridgedEdges], hubNodeIds: subgraph.hubNodeIds }
}
