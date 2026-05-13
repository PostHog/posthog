import { Edge, Node } from '@xyflow/react'
import type { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk.bundled.js'

import { getElk } from 'lib/elk'

export const GRAPH_NODE_WIDTH = 220
export const GRAPH_NODE_HEIGHT = 80

const ELK_OPTIONS = {
    'elk.algorithm': 'force',
    'elk.force.iterations': '300',
    'elk.force.repulsivePower': '1',
    'elk.padding': '[left=40, top=40, right=40, bottom=40]',
    'elk.spacing.nodeNode': '60',
    'elk.separateConnectedComponents': 'true',
}

export async function applyForceLayout(nodes: Node[], edges: Edge[]): Promise<Node[]> {
    if (nodes.length === 0) {
        return []
    }
    const root: ElkNode = {
        id: 'root',
        layoutOptions: ELK_OPTIONS,
        children: nodes.map((n) => ({
            id: n.id,
            width: GRAPH_NODE_WIDTH,
            height: GRAPH_NODE_HEIGHT,
        })),
        edges: edges.map((e) => ({
            id: e.id,
            sources: [e.source],
            targets: [e.target],
        })) as ElkExtendedEdge[],
    }
    const laidOut = await (await getElk()).layout(root)
    const positions = new Map<string, { x: number; y: number }>()
    for (const c of laidOut.children ?? []) {
        positions.set(c.id, { x: c.x ?? 0, y: c.y ?? 0 })
    }
    return nodes.map((n) => ({ ...n, position: positions.get(n.id) ?? { x: 0, y: 0 } }))
}
