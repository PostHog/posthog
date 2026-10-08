import { BIConditionGroup, BIResultFilter } from '~/queries/schema/schema-business-intelligence'

export function isBIConditionGroup(value: unknown, depth = 0): value is BIConditionGroup {
    if (!value || typeof value !== 'object' || depth > 8) {
        return false
    }
    const group = value as BIConditionGroup
    return (
        ['AND', 'OR'].includes(group.operator) &&
        Array.isArray(group.filters) &&
        group.filters.every((id) => typeof id === 'string') &&
        Array.isArray(group.groups) &&
        group.groups.every((child) => isBIConditionGroup(child, depth + 1))
    )
}

export function isBIResultFilter(value: unknown): value is BIResultFilter {
    if (!value || typeof value !== 'object') {
        return false
    }
    const filter = value as BIResultFilter
    return (
        typeof filter.id === 'string' &&
        Number.isInteger(filter.measureIndex) &&
        filter.measureIndex >= 0 &&
        [
            'equals',
            'not_equals',
            'greater_than',
            'less_than',
            'greater_than_or_equal',
            'less_than_or_equal',
            'between',
            'is_set',
            'is_not_set',
        ].includes(filter.operator) &&
        typeof filter.value === 'string' &&
        (filter.valueTo === undefined || typeof filter.valueTo === 'string') &&
        (filter.enabled === undefined || typeof filter.enabled === 'boolean')
    )
}

export function normalizeBIConditionGroup(group: BIConditionGroup | undefined, ids: string[]): BIConditionGroup {
    const remaining = new Set(ids)
    const visit = (node: BIConditionGroup): BIConditionGroup => ({
        operator: node.operator,
        filters: node.filters.filter((id) => remaining.delete(id)),
        groups: node.groups.map(visit),
    })
    const normalized = visit(group ?? { operator: 'AND', filters: [], groups: [] })
    return { ...normalized, filters: [...normalized.filters, ...remaining] }
}

export function buildBIConditionExpression(
    group: BIConditionGroup,
    expressions: Map<string, string | null>
): string | null {
    const parts = [
        ...group.filters.map((id) => expressions.get(id)),
        ...group.groups.map((child) => buildBIConditionExpression(child, expressions)),
    ].filter((part): part is string => !!part)
    return parts.length ? parts.map((part) => `(${part})`).join(` ${group.operator} `) : null
}

export function updateBIConditionGroup(
    group: BIConditionGroup,
    path: number[],
    update: (node: BIConditionGroup) => BIConditionGroup
): BIConditionGroup {
    return path.length
        ? {
              ...group,
              groups: group.groups.map((child, index) =>
                  index === path[0] ? updateBIConditionGroup(child, path.slice(1), update) : child
              ),
          }
        : update(group)
}

export function moveBICondition(group: BIConditionGroup, id: string, path: number[]): BIConditionGroup {
    const remove = (node: BIConditionGroup): BIConditionGroup => ({
        ...node,
        filters: node.filters.filter((filter) => filter !== id),
        groups: node.groups.map(remove),
    })
    return updateBIConditionGroup(remove(group), path, (node) => ({ ...node, filters: [...node.filters, id] }))
}

export function ungroupBIConditionGroup(root: BIConditionGroup, path: number[]): BIConditionGroup {
    if (!path.length) {
        return root
    }
    return updateBIConditionGroup(root, path.slice(0, -1), (parent) => {
        const index = path[path.length - 1]
        const group = parent.groups[index]
        return group
            ? {
                  ...parent,
                  filters: [...parent.filters, ...group.filters],
                  groups: parent.groups.flatMap((child, childIndex) => (childIndex === index ? group.groups : [child])),
              }
            : parent
    })
}
