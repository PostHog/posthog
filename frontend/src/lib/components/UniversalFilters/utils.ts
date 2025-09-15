import {
    ActionFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FilterLogicalOperator,
    LogEntryPropertyFilter,
    PropertyFilterType,
    RecordingPropertyFilter,
    UniversalFilterValue,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { isCohortPropertyFilter } from '../PropertyFilters/utils'

export function isUniversalGroupFilterLike(filter?: UniversalFiltersGroupValue): filter is UniversalFiltersGroup {
    return filter?.type === FilterLogicalOperator.And || filter?.type === FilterLogicalOperator.Or
}
export function isEntityFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return isEventFilter(filter) || isActionFilter(filter)
}
export function isEventFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return filter.type === 'events'
}
export function isEventPropertyFilter(filter: UniversalFilterValue): filter is EventPropertyFilter {
    return filter.type === PropertyFilterType.Event
}
export function isActionFilter(filter: UniversalFilterValue): filter is ActionFilter {
    return filter.type === 'actions'
}
export function isFeatureFlagFilter(filter: UniversalFilterValue): filter is FeaturePropertyFilter {
    return filter.type === 'feature'
}
export function isRecordingPropertyFilter(filter: UniversalFilterValue): filter is RecordingPropertyFilter {
    return filter.type === 'recording'
}
export function isLogEntryPropertyFilter(filter: UniversalFilterValue): filter is LogEntryPropertyFilter {
    return filter.type === 'log_entry'
}
export function isEditableFilter(filter: UniversalFilterValue): boolean {
    return isEntityFilter(filter) ? false : !isCohortPropertyFilter(filter)
}
export function isCommentTextFilter(filter: UniversalFiltersGroupValue): boolean {
    return (
        !isUniversalGroupFilterLike(filter) &&
        filter.type === PropertyFilterType.Recording &&
        filter.key === 'comment_text'
    )
}
