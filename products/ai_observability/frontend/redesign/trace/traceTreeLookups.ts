import type { TraceNodeApi } from '../../generated/api.schemas'
import { EvalRollupOutcome, TreeStep } from './types'

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

function parentOf(nodes: TraceNodeApi[], id: string, parent: TraceNodeApi | null = null): TraceNodeApi | null {
    for (const node of nodes) {
        const found = node.id === id ? parent : parentOf(node.children, id, node)
        if (found) {
            return found
        }
    }
    return null
}

/**
 * The step a move from `nodeId` lands on, or null when the move leads nowhere: past either end, up from a root, or
 * down from a step without children. An id outside the tree has no place to move from, so any move lands on the
 * first step.
 */
export function steppedNodeId(tree: TraceNodeApi[], nodeId: string, step: TreeStep): string | null {
    const nodes = flattenTree(tree)
    const index = nodes.findIndex((node) => node.id === nodeId)
    if (index === -1) {
        return nodes[0]?.id ?? null
    }
    const targets: Record<TreeStep, TraceNodeApi | null | undefined> = {
        next: nodes[index + 1],
        previous: nodes[index - 1],
        first: nodes[0],
        last: nodes[nodes.length - 1],
        parent: parentOf(tree, nodeId),
        child: nodes[index].children[0],
    }
    const target = targets[step]
    return target && target.id !== nodeId ? target.id : null
}

export function stepLabelsOf(tree: TraceNodeApi[]): ReadonlyMap<string, string> {
    return new Map(flattenTree(tree).map((node) => [node.id, node.label]))
}

export function firstFailingNodeId(
    tree: TraceNodeApi[],
    outcomes: ReadonlyMap<string, EvalRollupOutcome>
): string | null {
    return flattenTree(tree).find((node) => outcomes.get(node.id) === 'fail')?.id ?? null
}
