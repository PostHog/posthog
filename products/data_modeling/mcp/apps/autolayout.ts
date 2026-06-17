// ELK `layered` auto-layout for the data model DAG. Ported and simplified from
// frontend/src/scenes/data-warehouse/scene/modeling/autolayout.ts — the `getElk`
// (lib/elk) and NODE_WIDTH/HEIGHT (modeling/constants) dependencies are inlined so
// the UI app bundle is self-contained.

import ELK, { type ElkExtendedEdge, type ElkNode } from 'elkjs/lib/elk.bundled.js'

import type { DataModelEdge, DataModelNode } from './types'

export const NODE_WIDTH = 200
export const NODE_HEIGHT = 96

let elkInstance: InstanceType<typeof ELK> | null = null
function getElk(): InstanceType<typeof ELK> {
    if (!elkInstance) {
        elkInstance = new ELK()
    }
    return elkInstance
}

export interface NodePosition {
    x: number
    y: number
}

const ELK_OPTIONS = {
    'elk.algorithm': 'layered',
    'elk.direction': 'RIGHT',
    'elk.edgeRouting': 'ORTHOGONAL',
    'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    'elk.layered.cycleBreaking.strategy': 'GREEDY',
    'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
    'elk.layered.mergeEdges': 'true',
    'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    'elk.layered.spacing.nodeNodeBetweenLayers': '80',
    'elk.separateConnectedComponents': 'true',
    'elk.spacing.edgeNode': '30',
    'elk.spacing.nodeNode': '40',
}

/** Run ELK layered layout left-to-right; returns a map of node id -> {x, y}. */
export async function layoutGraph(
    nodes: DataModelNode[],
    edges: DataModelEdge[]
): Promise<Record<string, NodePosition>> {
    if (nodes.length === 0) {
        return {}
    }

    const graph: ElkNode = {
        id: 'root',
        layoutOptions: ELK_OPTIONS,
        children: nodes.map((node) => ({
            id: node.id,
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
        })),
        edges: edges.map(
            (edge): ElkExtendedEdge => ({
                id: edge.id,
                sources: [edge.source_id],
                targets: [edge.target_id],
            })
        ),
    }

    const laidOut = await getElk().layout(graph)
    const positions: Record<string, NodePosition> = {}
    for (const child of laidOut.children ?? []) {
        positions[child.id] = { x: child.x ?? 0, y: child.y ?? 0 }
    }
    return positions
}
