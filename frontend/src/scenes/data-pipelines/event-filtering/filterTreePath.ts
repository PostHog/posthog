/** Path navigation utilities for the filter expression tree. */
import type { FilterNode, TreePath } from './eventFilterLogic'

/** Walk a TreePath from root and return the node at the end, or undefined if the path is invalid. */
export function getNodeAtPath(tree: FilterNode, path: TreePath): FilterNode | undefined {
    let current: FilterNode | undefined = tree
    for (const step of path) {
        if (!current) {
            return undefined
        }
        if (typeof step === 'number' && (current.type === 'and' || current.type === 'or')) {
            current = current.children[step]
        } else if (step === 'child' && current.type === 'not') {
            current = current.child
        } else {
            return undefined
        }
    }
    return current
}

/**
 * Split a path into the parent group's path and the child's index within it.
 * Returns null for root paths or paths ending with 'child' (NOT nodes don't
 * have a numeric index). Used to find which group a dragged node belongs to.
 */
export function splitParentChild(path: TreePath): { parentPath: TreePath; childIndex: number } | null {
    if (path.length === 0) {
        return null
    }
    const last = path[path.length - 1]
    if (typeof last !== 'number') {
        return null
    }
    return { parentPath: path.slice(0, -1), childIndex: last }
}

/** True if path `a` is a strict prefix of path `b` (a is an ancestor of b). */
export function isAncestorPath(a: TreePath, b: TreePath): boolean {
    if (a.length >= b.length) {
        return false
    }
    return a.every((seg, i) => seg === b[i])
}
