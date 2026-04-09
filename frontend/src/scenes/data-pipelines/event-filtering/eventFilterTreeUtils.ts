import type { FilterNode, TreePath } from './eventFilterLogic'

// --- Stable node IDs ---
// Each node gets a `_nid` property. We stamp them when first seen and preserve
// them across tree mutations. This means DnD IDs don't change when indices shift.

let nidCounter = 0
function nextNid(): string {
    return `n${nidCounter++}`
}

type AnyNode = FilterNode & { _nid?: string }

/** Ensure every node in the tree has a stable `_nid`. Mutates in place. */
export function stampNids(node: AnyNode): void {
    if (!node._nid) {
        node._nid = nextNid()
    }
    if (node.type === 'and' || node.type === 'or') {
        for (const child of node.children) {
            stampNids(child as AnyNode)
        }
    } else if (node.type === 'not') {
        stampNids(node.child as AnyNode)
    }
}

/** Get the _nid of a node */
export function nid(node: FilterNode): string {
    return (node as AnyNode)._nid ?? ''
}

/** Build a map from _nid → tree path */
export type NidIndex = Map<string, TreePath>

export function buildNidIndex(node: FilterNode, path: TreePath = []): NidIndex {
    const index: NidIndex = new Map()
    const id = nid(node)
    if (id) {
        index.set(id, path)
    }
    if (node.type === 'and' || node.type === 'or') {
        for (let i = 0; i < node.children.length; i++) {
            const childIndex = buildNidIndex(node.children[i], [...path, i])
            for (const [k, v] of childIndex) {
                index.set(k, v)
            }
        }
    } else if (node.type === 'not') {
        const childIndex = buildNidIndex(node.child, [...path, 'child'])
        for (const [k, v] of childIndex) {
            index.set(k, v)
        }
    }
    return index
}

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

export function isAncestorPath(a: TreePath, b: TreePath): boolean {
    if (a.length >= b.length) {
        return false
    }
    return a.every((seg, i) => seg === b[i])
}

export function isTreeEmpty(node: FilterNode): boolean {
    if (!node?.type) {
        return true
    }
    if (node.type === 'condition') {
        return false
    }
    if (node.type === 'not') {
        return isTreeEmpty(node.child)
    }
    return node.children.length === 0
}

export function filterTreeToExpression(node: FilterNode, indent: number = 0): string {
    const pad = '  '.repeat(indent)
    switch (node.type) {
        case 'condition': {
            const op = node.operator === 'exact' ? '=' : '~'
            return `${pad}${node.field} ${op} "${node.value}"`
        }
        case 'not': {
            const inner = filterTreeToExpression(node.child, indent + 1)
            const isSimple = node.child.type === 'condition'
            if (isSimple) {
                return `${pad}NOT (${inner.trim()})`
            }
            return `${pad}NOT (\n${inner}\n${pad})`
        }
        case 'and':
        case 'or': {
            if (node.children.length === 0) {
                return `${pad}(empty)`
            }
            if (node.children.length === 1) {
                return filterTreeToExpression(node.children[0], indent)
            }
            const joiner = node.type === 'and' ? 'AND' : 'OR'
            const parts = node.children.map((child) => {
                const needsParens = (child.type === 'and' || child.type === 'or') && child.type !== node.type
                if (needsParens) {
                    const innerParts = child.children.map((c) => filterTreeToExpression(c, indent + 1))
                    const innerJoiner = child.type === 'and' ? 'AND' : 'OR'
                    const inner = innerParts.join(`\n${pad}  ${innerJoiner}\n`)
                    return `${pad}(\n${inner}\n${pad})`
                }
                return filterTreeToExpression(child, indent)
            })
            return parts.join(`\n${pad}${joiner}\n`)
        }
    }
}

export function nodeSummary(node: FilterNode): string {
    if (node.type === 'condition') {
        return `${node.field} ${node.operator} "${node.value}"`
    }
    if (node.type === 'not') {
        return 'NOT (...)'
    }
    return `${node.type.toUpperCase()} group (${node.children.length} items)`
}
