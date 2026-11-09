import { FilterLogicalOperator } from '~/types'

export const AND_OR_FILTER_OPTIONS = [
    {
        value: FilterLogicalOperator.And,
        label: 'all',
        title: 'All',
        description: 'Every single filter must match',
    },
    {
        value: FilterLogicalOperator.Or,
        label: 'any',
        title: 'Any',
        description: 'One or more filters must match',
    },
] as const

export function andOrFilterSuffix(value: FilterLogicalOperator, suffix: [singular: string, plural: string]): string {
    return value === FilterLogicalOperator.Or ? suffix[0] : suffix[1]
}
