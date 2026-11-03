import {
    ActionFilter,
    AnyPropertyFilter,
    EntityTypes,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { filterOperator, filterValues, isFilterComplete } from './filterBarFields'
import { FilterBarEventNode, FilterBarGroupNode, FilterBarItem, FilterBarNode, FilterBarValue } from './filterBarTypes'

/** The bar joins its top-level nodes with AND, so an OR at the top of a stored filter becomes one group chip. */
export interface FilterBarTree {
    nextId: number
    nodes: FilterBarNode[]
}

export function isGroupNode(node: FilterBarNode): node is FilterBarGroupNode {
    return 'children' in node
}

export function isEventNode(node: FilterBarNode): node is FilterBarEventNode {
    return 'event' in node
}

export function isItemNode(node: FilterBarNode): node is FilterBarItem {
    return 'filter' in node
}

function isGroupValue(value: UniversalFiltersGroupValue): value is UniversalFiltersGroup {
    return value.type === FilterLogicalOperator.And || value.type === FilterLogicalOperator.Or
}

function isEventValue(value: UniversalFiltersGroupValue): value is ActionFilter {
    return value.type === EntityTypes.EVENTS || value.type === EntityTypes.ACTIONS
}

function sameProperty(a: AnyPropertyFilter, b: AnyPropertyFilter): boolean {
    return (
        a.type === b.type &&
        a.key === b.key &&
        (a as { group_type_index?: number }).group_type_index === (b as { group_type_index?: number }).group_type_index
    )
}

/**
 * "Country is FR or country is GB" is one "is any of" chip, and "is not FR and is not GB" is one "is none of" chip.
 * The opposite pairs mean something else, so they stay separate rows.
 */
function mergeableOperator(type: FilterLogicalOperator): PropertyOperator {
    return type === FilterLogicalOperator.Or ? PropertyOperator.Exact : PropertyOperator.IsNot
}

function mergeSameProperty(
    values: UniversalFiltersGroupValue[],
    type: FilterLogicalOperator
): UniversalFiltersGroupValue[] {
    const operator = mergeableOperator(type)
    const merged: UniversalFiltersGroupValue[] = []
    for (const value of values) {
        if (isGroupValue(value) || isEventValue(value) || value.type === PropertyFilterType.Cohort) {
            merged.push(value)
            continue
        }
        const index = merged.findIndex(
            (candidate) =>
                !isGroupValue(candidate) &&
                !isEventValue(candidate) &&
                sameProperty(candidate, value) &&
                filterOperator(candidate) === operator &&
                filterOperator(value) === operator
        )
        if (index === -1) {
            merged.push(value)
            continue
        }
        const existing = merged[index] as AnyPropertyFilter
        merged[index] = {
            ...existing,
            value: Array.from(new Set([...filterValues(existing), ...filterValues(value)].map(String))),
        } as AnyPropertyFilter
    }
    return merged
}

/** Whether this AND row asks one property to equal values no earlier sibling allows, which matches nothing. */
export function contradictsEarlierSibling(rows: FilterBarNode[], index: number, type: FilterLogicalOperator): boolean {
    const row = rows[index]
    if (
        type !== FilterLogicalOperator.And ||
        !isItemNode(row) ||
        filterOperator(row.filter) !== PropertyOperator.Exact
    ) {
        return false
    }
    const values = filterValues(row.filter).map(String)
    return rows.slice(0, index).some((sibling) => {
        if (!isItemNode(sibling) || !sameProperty(sibling.filter, row.filter)) {
            return false
        }
        const earlier = filterValues(sibling.filter).map(String)
        return (
            filterOperator(sibling.filter) === PropertyOperator.Exact &&
            earlier.length > 0 &&
            values.length > 0 &&
            !values.some((value) => earlier.includes(value))
        )
    })
}

/** A nested group with its parent's operator adds nothing, and one with a single row is that row. */
function inlineValues(
    values: UniversalFiltersGroupValue[],
    operator: FilterLogicalOperator
): UniversalFiltersGroupValue[] {
    return values.flatMap((value) => {
        if (!isGroupValue(value)) {
            return isEventValue(value) || value.key != null ? [value] : []
        }
        const inlined = mergeSameProperty(inlineValues(value.values, value.type), value.type)
        return value.type === operator || inlined.length <= 1 ? inlined : [{ ...value, values: inlined }]
    })
}

export function treeFromValue(value: FilterBarValue, firstId = 0): FilterBarTree {
    let nextId = firstId
    const item = (filter: AnyPropertyFilter): FilterBarItem => ({ id: nextId++, filter })
    const node = (row: UniversalFiltersGroupValue): FilterBarNode => {
        if (isGroupValue(row)) {
            return { id: nextId++, type: row.type, children: row.values.map(node) }
        }
        if (isEventValue(row)) {
            const { properties, ...event } = row
            return { id: nextId++, event, items: (properties ?? []).map(item) }
        }
        return item(row)
    }
    const rows = mergeSameProperty(
        inlineValues(Array.isArray(value) ? value : [value], FilterLogicalOperator.And),
        FilterLogicalOperator.And
    )
    return { nodes: rows.map(node), nextId }
}

function valueFromNode(node: FilterBarNode): UniversalFiltersGroupValue | null {
    if (isItemNode(node)) {
        return isFilterComplete(node.filter) ? node.filter : null
    }
    if (isEventNode(node)) {
        const properties = node.items.map((item) => item.filter).filter(isFilterComplete)
        return properties.length > 0 ? { ...node.event, properties } : node.event
    }
    const values = node.children.flatMap((child) => {
        const value = valueFromNode(child)
        if (!value) {
            return []
        }
        return isGroupValue(value) && value.type === node.type ? value.values : [value]
    })
    if (values.length <= 1) {
        return values[0] ?? null
    }
    return { type: node.type, values }
}

/**
 * The complete part of the tree in its one canonical shape: a top-level AND over groups, with neighboring rows in one
 * AND group. Two values that mean the same thing compare equal in this shape, so a parent echoing a change back does
 * not rebuild the tree.
 */
export function valueFromNodes(nodes: FilterBarNode[]): UniversalFiltersGroup {
    const values: UniversalFiltersGroup[] = []
    let rows: UniversalFiltersGroupValue[] = []
    const flushRows = (): void => {
        if (rows.length > 0) {
            values.push({ type: FilterLogicalOperator.And, values: rows })
            rows = []
        }
    }
    for (const node of nodes) {
        const value = valueFromNode(node)
        if (value && isGroupValue(value) && value.type === FilterLogicalOperator.Or) {
            flushRows()
            values.push(value)
        } else if (value) {
            rows.push(...(isGroupValue(value) ? value.values : [value]))
        }
    }
    flushRows()
    return { type: FilterLogicalOperator.And, values }
}

export function leafItems(nodes: FilterBarNode[]): FilterBarItem[] {
    return nodes.flatMap((node) => {
        if (isItemNode(node)) {
            return [node]
        }
        return isEventNode(node) ? node.items : leafItems(node.children)
    })
}

export function findNode(nodes: FilterBarNode[], id: number): FilterBarNode | null {
    for (const node of nodes) {
        if (node.id === id) {
            return node
        }
        const nested = isGroupNode(node) ? node.children : isEventNode(node) ? node.items : []
        const match = findNode(nested, id)
        if (match) {
            return match
        }
    }
    return null
}

export function findParentGroupId(nodes: FilterBarNode[], id: number): number | null {
    for (const node of nodes) {
        if (isGroupNode(node)) {
            if (node.children.some((child) => child.id === id)) {
                return node.id
            }
            const nested = findParentGroupId(node.children, id)
            if (nested != null) {
                return nested
            }
        }
    }
    return null
}

/** Every filter and event in the tree, which is what a person counts as a condition. */
export function conditionCount(nodes: FilterBarNode[]): number {
    return nodes.reduce((count, node) => {
        if (isGroupNode(node)) {
            return count + conditionCount(node.children)
        }
        return count + 1 + (isEventNode(node) ? node.items.length : 0)
    }, 0)
}

/** A copy with fresh ids, so React keys and edits never reach the original. */
export function cloneNode(node: FilterBarNode, firstId: number): { node: FilterBarNode; nextId: number } {
    let nextId = firstId
    const copy = (original: FilterBarNode): FilterBarNode => {
        const id = nextId++
        if (isGroupNode(original)) {
            return { ...original, id, children: original.children.map(copy) }
        }
        if (isEventNode(original)) {
            return { ...original, id, items: original.items.map(copy) as FilterBarItem[] }
        }
        return { ...original, id }
    }
    return { node: copy(node), nextId }
}

/** Returning null from `update` removes the node, and returning a list puts those nodes in its place. */
export function updateNode(
    nodes: FilterBarNode[],
    id: number,
    update: (node: FilterBarNode) => FilterBarNode | FilterBarNode[] | null
): FilterBarNode[] {
    return nodes.flatMap((node) => {
        if (node.id === id) {
            const updated = update(node)
            return updated ?? []
        }
        if (isGroupNode(node)) {
            return [{ ...node, children: updateNode(node.children, id, update) }]
        }
        if (isEventNode(node)) {
            return [{ ...node, items: updateNode(node.items, id, update) as FilterBarItem[] }]
        }
        return [node]
    })
}

export function updateItemFilter(
    nodes: FilterBarNode[],
    id: number,
    update: (filter: AnyPropertyFilter) => AnyPropertyFilter
): FilterBarNode[] {
    return updateNode(nodes, id, (node) => (isItemNode(node) ? { ...node, filter: update(node.filter) } : node))
}

/** The rows a new filter joins: the top level, or the group or event the add menu was opened from. */
export function targetChildren(nodes: FilterBarNode[], targetId: number | null): FilterBarNode[] {
    const target = targetId != null ? findNode(nodes, targetId) : null
    if (!target) {
        return nodes
    }
    return isGroupNode(target) ? target.children : isEventNode(target) ? target.items : nodes
}

export function appendToTarget(nodes: FilterBarNode[], targetId: number | null, added: FilterBarNode): FilterBarNode[] {
    const target = targetId != null ? findNode(nodes, targetId) : null
    if (!target || isItemNode(target)) {
        return [...nodes, added]
    }
    return updateNode(nodes, target.id, (node) => {
        if (isGroupNode(node)) {
            return { ...node, children: [...node.children, added] }
        }
        return isEventNode(node) && isItemNode(added) ? { ...node, items: [...node.items, added] } : node
    })
}

/** The most rows the bar shows as chips. Past this, or with any nesting, one summary chip opens the stacked editor. */
export const MAX_INLINE_ROWS = 3

export function needsStackedEditor(nodes: FilterBarNode[]): boolean {
    return (
        nodes.length > MAX_INLINE_ROWS ||
        nodes.some((node) => isGroupNode(node) || (isEventNode(node) && node.items.length > 0))
    )
}

/** A group left with one row is that row, and a group left with none is gone. */
export function pruneGroups(nodes: FilterBarNode[]): FilterBarNode[] {
    return nodes.flatMap((node) => {
        if (!isGroupNode(node)) {
            return [node]
        }
        const children = pruneGroups(node.children)
        return children.length > 1 ? [{ ...node, children }] : children
    })
}
