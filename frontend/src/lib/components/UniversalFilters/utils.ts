import { FilterLogicalOperator } from '~/types'

import { UniversalGroupFilterGroup, UniversalGroupFilterValue } from './UniversalFilters'

export function isUniversalGroupFilterLike(filter?: UniversalGroupFilterValue): filter is UniversalGroupFilterGroup {
    return filter?.type === FilterLogicalOperator.And || filter?.type === FilterLogicalOperator.Or
}
