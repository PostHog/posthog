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

// Two steps can share a name, such as two calls to the same model, so repeated names get their position.
export function nodeLabels(tree: TraceNodeApi[]): Map<string, string> {
    const nodes = flattenTree(tree)
    const totals = new Map<string, number>()
    nodes.forEach((node) => totals.set(node.name, (totals.get(node.name) ?? 0) + 1))
    const seen = new Map<string, number>()
    return new Map(
        nodes.map((node) => {
            const position = (seen.get(node.name) ?? 0) + 1
            seen.set(node.name, position)
            return [node.id, (totals.get(node.name) ?? 0) > 1 ? `${node.name} #${position}` : node.name]
        })
    )
}
