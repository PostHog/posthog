import { ActionFilter, FilterLogicalOperator } from '~/types'

import { isCohortPropertyFilter } from '../PropertyFilters/utils'
import { UniversalFiltersGroup, UniversalFiltersGroupValue, UniversalFilterValue } from './UniversalFilters'

export function isUniversalGroupFilterLike(filter?: UniversalFiltersGroupValue): filter is UniversalFiltersGroup {
    return filter?.type === FilterLogicalOperator.And || filter?.type === FilterLogicalOperator.Or
}

export function isEntityFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return isEventFilter(filter) || isActionFilter(filter)
}

export function isEventFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return filter.type === 'events'
}

export function isActionFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return filter.type === 'actions'
}

export function isEditableFilter(filter: UniversalFilterValue): boolean {
    return isEntityFilter(filter) ? false : !isCohortPropertyFilter(filter)
}
