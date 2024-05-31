import { FilterLogicalOperator } from '~/types'

import { UniversalGroupFilter, UniversalGroupFilterValue } from './UniversalFilters'

export function isUniversalGroupFilterLike(
    filter?: UniversalGroupFilter | UniversalGroupFilterValue | null
): filter is UniversalGroupFilter | UniversalGroupFilterValue {
    return filter?.type === FilterLogicalOperator.And || filter?.type === FilterLogicalOperator.Or
}
