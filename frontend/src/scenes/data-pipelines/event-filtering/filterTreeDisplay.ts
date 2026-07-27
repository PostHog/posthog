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
    return node.children.length === 0 || node.children.every(isTreeEmpty)
}

/**
 * Render the filter tree as a human-readable tree diagram.
 * Used in the "Show expression" modal. Example output:
 *
 *   OR
 *   ├── event_name = "$drop_me"
 *   └── AND
 *       ├── event_name = "$internal"
 *       └── distinct_id ~ "bot-"
 *
 * `indent` is the whitespace prefix for continuation lines (children).
 * The node's own label is rendered without indent — the caller prepends
 * the connector (├── or └──) and indent.
 */
function renderNode(node: FilterNode, indent: string): string {
    switch (node.type) {
        case 'condition': {
            const op = node.operator === 'exact' ? '=' : '~'
            return `${node.field} ${op} "${node.value}"`
        }
        case 'not': {
            const childLine = renderNode(node.child, indent + '    ')
            return `NOT\n${indent}└── ${childLine}`
        }
        case 'and':
        case 'or': {
            if (node.children.length === 0) {
                return `${node.type.toUpperCase()} (empty)`
            }
            const lines = node.children.map((child, i) => {
                const isLast = i === node.children.length - 1
                const connector = isLast ? '└── ' : '├── '
                const childIndent = indent + (isLast ? '    ' : '│   ')
                return `${indent}${connector}${renderNode(child, childIndent)}`
            })
            return `${node.type.toUpperCase()}\n${lines.join('\n')}`
        }
    }
}

/**
 * Render the filter tree as a human-readable tree diagram.
 * Used in the "Show expression" modal.
 */
export function filterTreeToExpression(node: FilterNode): string {
    return renderNode(node, '')
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
