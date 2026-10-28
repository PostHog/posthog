import { DataModelingEdge, DataModelingNode } from '~/types'

import { AdjacencyMaps, buildAdjacencyMaps, edgesWithinNodes } from './lineageSearch'

export const HIDDEN_DOWNSTREAM_COUNT_CAP = 99

const PATH_COUNT_CEILING = 1_000_000
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
    hiddenDownstreamCounts: Map<string, number>
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
    private readonly reachedTerminals = new Map<string, ReadonlySet<string>>()
    private readonly deadEndsBelow = new Map<string, ReadonlySet<string>>()

    constructor(
        scopedEdges: DataModelingEdge[],
        private readonly scopeNodeIds: Set<string>,
        private readonly visibleNodeIds: Set<string>
    ) {
        this.maps = buildAdjacencyMaps(scopedEdges)
        this.hubNodeIds = this.findHubs()
        this.terminals = new Set([...visibleNodeIds, ...this.hubNodeIds])
        this.walkHiddenNodes()
    }

    terminalsReachedFrom(sourceId: string): Set<string> {
        const reached = new Set<string>()
        for (const childId of this.hiddenChildren(sourceId)) {
            this.reachedTerminals.get(childId)?.forEach((targetId) => reached.add(targetId))
        }
        reached.delete(sourceId)
        return reached
    }

    deadEndCountBelow(sourceId: string): number {
        const deadEnds = new Set<string>()
        for (const childId of this.hiddenChildren(sourceId)) {
            addCapped(deadEnds, this.deadEndsBelow.get(childId) ?? EMPTY_NODE_IDS)
        }
        return deadEnds.size
    }

    private isHidden = (nodeId: string): boolean => !this.visibleNodeIds.has(nodeId)

    private isHiddenNonTerminal = (nodeId: string): boolean => !this.terminals.has(nodeId)

    private hiddenChildren(nodeId: string): string[] {
        return (this.maps.downstream.get(nodeId) ?? []).filter(this.isHiddenNonTerminal)
    }

    private findHubs(): Set<string> {
        const upstreamPaths = this.countVisiblePaths(this.maps.upstream)
        const downstreamPaths = this.countVisiblePaths(this.maps.downstream)
        return new Set(
            [...upstreamPaths.keys()].filter((nodeId) => {
                const upstream = upstreamPaths.get(nodeId) ?? 0
                const downstream = downstreamPaths.get(nodeId) ?? 0
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
            const reached = this.collectReachedTerminals(nodeId)
            this.reachedTerminals.set(nodeId, reached)
            const deadEnds = new Set<string>(reached.size === 0 ? [nodeId] : [])
            for (const childId of this.hiddenChildren(nodeId)) {
                addCapped(deadEnds, this.deadEndsBelow.get(childId) ?? EMPTY_NODE_IDS)
            }
            this.deadEndsBelow.set(nodeId, deadEnds)
        }
    }

    private collectReachedTerminals(nodeId: string): ReadonlySet<string> {
        const terminalChildren = (this.maps.downstream.get(nodeId) ?? []).filter((childId) =>
            this.terminals.has(childId)
        )
        const hiddenChildReach = this.hiddenChildren(nodeId)
            .map((childId) => this.reachedTerminals.get(childId) ?? EMPTY_NODE_IDS)
            .filter((reached) => reached.size > 0)
        if (terminalChildren.length === 0 && hiddenChildReach.length === 1) {
            return hiddenChildReach[0]
        }
        return new Set([...terminalChildren, ...hiddenChildReach.flatMap((childReach) => [...childReach])])
    }
}

function addCapped(target: Set<string>, source: ReadonlySet<string>): void {
    for (const nodeId of source) {
        if (target.size > HIDDEN_DOWNSTREAM_COUNT_CAP) {
            return
        }
        target.add(nodeId)
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
            hiddenDownstreamCounts: new Map(),
        }
    }

    const subgraph = new HiddenSubgraph(edgesWithinNodes(edges, scopeNodeIds), scopeNodeIds, visibleNodeIds)
    const realEdges = edgesWithinNodes(edges, subgraph.terminals)
    const realEdgeKeys = new Set(realEdges.map((edge) => edgeKey(edge.source_id, edge.target_id)))
    const bridgedEdges: LineageEdge[] = []
    const hiddenDownstreamCounts = new Map<string, number>()

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

    for (const sourceId of visibleNodeIds) {
        const deadEndCount = subgraph.deadEndCountBelow(sourceId)
        if (deadEndCount > 0) {
            hiddenDownstreamCounts.set(sourceId, deadEndCount)
        }
    }

    return { edges: [...realEdges, ...bridgedEdges], hubNodeIds: subgraph.hubNodeIds, hiddenDownstreamCounts }
}
