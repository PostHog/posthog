import type { FilterNode } from './eventFilterLogic'

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
export type NidIndex = Map<string, (string | number)[]>

export function buildNidIndex(node: FilterNode, path: (string | number)[] = []): NidIndex {
    const index: NidIndex = new Map()
    const id = nid(node)
    if (id) {
        index.set(id, path)
    }
    if (node.type === 'and' || node.type === 'or') {
        for (let i = 0; i < node.children.length; i++) {
            const childIndex = buildNidIndex(node.children[i], [...path, 'children', i])
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

export function getNodeAtPath(tree: FilterNode, path: (string | number)[]): FilterNode | undefined {
    let current: unknown = tree
    for (const key of path) {
        if (current == null) {
            return undefined
        }
        current = (current as Record<string | number, unknown>)[key]
    }
    return current as FilterNode | undefined
}

export function splitParentChild(
    path: (string | number)[]
): { parentPath: (string | number)[]; childIndex: number } | null {
    if (path.length < 2) {
        return null
    }
    const childIndex = path[path.length - 1]
    if (typeof childIndex !== 'number') {
        return null
    }
    return { parentPath: path.slice(0, -2), childIndex }
}

export function isAncestorPath(a: (string | number)[], b: (string | number)[]): boolean {
    if (a.length >= b.length) {
        return false
    }
    return a.every((seg, i) => String(seg) === String(b[i]))
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
