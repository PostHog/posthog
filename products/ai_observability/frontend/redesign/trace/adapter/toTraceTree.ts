import type { TraceNodeApi } from '../../../generated/api.schemas'

export function findTreeNode(nodes: TraceNodeApi[], id: string): TraceNodeApi | null {
    for (const node of nodes) {
        if (node.id === id) {
            return node
        }
        const found = findTreeNode(node.children, id)
        if (found) {
            return found
        }
    }
    return null
}

/** Every node, each before its children, in tree order. */
export function flattenTree(nodes: TraceNodeApi[]): TraceNodeApi[] {
    return nodes.flatMap((node) => [node, ...flattenTree(node.children)])
}
