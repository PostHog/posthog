import { FilterConditionNode, FilterNode } from './schema'

/**
 * Recursively evaluate a filter tree node against event fields.
 *
 * SAFETY: Empty groups are conservative (never drop):
 * - Empty AND returns false (not vacuous true) to avoid dropping all events
 * - Empty OR returns false (no children match)
 * Note: NOT(empty group) evaluates to NOT(false) = true and WOULD drop events.
 * This is prevented upstream by the treeHasConditions guard in EventFilterManager,
 * which returns null for any filter tree that contains no condition leaves.
 * This is intentional — when in doubt, don't drop. Dropping is irreversible,
 * while not dropping just means unwanted events get through temporarily.
 */
export function evaluateFilterTree(node: FilterNode, event: { event_name?: string; distinct_id?: string }): boolean {
    switch (node.type) {
        case 'condition':
            return evaluateCondition(node, event)
        case 'and':
            // Guard: [].every() is true in JS (vacuous truth) which would drop everything
            return node.children.length > 0 && node.children.every((child) => evaluateFilterTree(child, event))
        case 'or':
            return node.children.some((child) => evaluateFilterTree(child, event))
        case 'not':
            return !evaluateFilterTree(node.child, event)
    }
}

function evaluateCondition(node: FilterConditionNode, event: { event_name?: string; distinct_id?: string }): boolean {
    const value = event[node.field]
    if (value === undefined || value === null) {
        return false
    }
    switch (node.operator) {
        case 'exact':
            return value === node.value
        case 'contains':
            return value.includes(node.value)
        default: {
            const _exhaustive: never = node.operator
            throw new Error(`Unknown filter operator: ${_exhaustive}`)
        }
    }
}

/** Check if a filter tree contains at least one condition leaf */
export function treeHasConditions(node: FilterNode): boolean {
    switch (node.type) {
        case 'condition':
            return true
        case 'not':
            return treeHasConditions(node.child)
        case 'and':
        case 'or':
            return node.children.some((child) => treeHasConditions(child))
    }
}
