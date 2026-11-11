import { FilterNode } from './schema'

export function cond(field: string, operator: string, value: string): FilterNode {
    return { type: 'condition', field, operator, value } as FilterNode
}

export function and(...children: FilterNode[]): FilterNode {
    return { type: 'and', children }
}

export function or(...children: FilterNode[]): FilterNode {
    return { type: 'or', children }
}

export function not(child: FilterNode): FilterNode {
    return { type: 'not', child }
}
