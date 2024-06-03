import {
    ActionFilter,
    AnyPropertyFilter,
    FilterLogicalOperator,
    FilterType,
    RecordingFilters,
    RecordingUniversalFilters,
} from '~/types'

import { isAnyPropertyfilter } from '../PropertyFilters/utils'
import { UniversalFilterValue, UniversalGroupFilterGroup, UniversalGroupFilterValue } from './UniversalFilters'

export function isUniversalGroupFilterLike(filter?: UniversalGroupFilterValue): filter is UniversalGroupFilterGroup {
    return filter?.type === FilterLogicalOperator.And || filter?.type === FilterLogicalOperator.Or
}

export function isActionFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return filter.type === 'events' || filter.type === 'actions'
}

export function convertUniversalFiltersToLegacyFilters(
    universalFilters: RecordingUniversalFilters
): RecordingFilters & { operand: FilterLogicalOperator } {
    const nestedFilters = universalFilters.filter_group.values[0] as UniversalGroupFilterGroup
    const operand = nestedFilters.type
    const filters = nestedFilters.values as UniversalFilterValue[]

    const properties: AnyPropertyFilter[] = []
    const events: FilterType['events'] = []
    const actions: FilterType['actions'] = []

    filters.forEach((f) => {
        if (isActionFilter(f)) {
            if (f.type === 'events') {
                events.push(f)
            } else if (f.type === 'actions') {
                actions.push(f)
            }
        } else if (isAnyPropertyfilter(f)) {
            properties.push(f)
        }
    })

    // TODO: add console log and duration filtering

    return {
        ...universalFilters,
        operand,
        properties,
        events,
        actions,
    }
}
