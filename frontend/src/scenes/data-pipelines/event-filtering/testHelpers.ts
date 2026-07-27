import { FilterNode, FilterConditionNode, FilterAndNode, FilterOrNode, FilterNotNode } from './eventFilterLogic'

export function cond(
    field: 'event_name' | 'distinct_id' = 'event_name',
    operator: 'exact' | 'contains' = 'exact',
    value: string = 'pageview'
): FilterConditionNode {
    return { type: 'condition', field, operator, value }
}

export function and(...children: FilterNode[]): FilterAndNode {
    return { type: 'and', children }
}

export function or(...children: FilterNode[]): FilterOrNode {
    return { type: 'or', children }
}

export function not(child: FilterNode): FilterNotNode {
    return { type: 'not', child }
}
