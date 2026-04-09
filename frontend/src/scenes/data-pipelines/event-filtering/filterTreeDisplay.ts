/** Display helpers for the filter expression tree. */
import type { FilterNode } from './eventFilterLogic'

/** True if the tree has no condition leaves (only empty groups or NOT wrappers). */
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

/**
 * Render the filter tree as a human-readable expression string.
 * Used in the "Show expression" modal. Example output:
 *
 *   event_name = "$drop_me"
 *   OR
 *   event_name = "$internal"
 *     AND
 *     distinct_id ~ "bot-"
 */
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

/** One-line summary of a node, shown in the DnD drag overlay. */
export function nodeSummary(node: FilterNode): string {
    if (node.type === 'condition') {
        return `${node.field} ${node.operator} "${node.value}"`
    }
    if (node.type === 'not') {
        return 'NOT (...)'
    }
    return `${node.type.toUpperCase()} group (${node.children.length} items)`
}
