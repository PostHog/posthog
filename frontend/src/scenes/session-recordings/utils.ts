import { LegacyRecordingFilters, RecordingUniversalFilters, UniversalFiltersGroup, UniversalFilterValue } from '~/types'

export const isUniversalFilters = (
    filters: RecordingUniversalFilters | LegacyRecordingFilters
): filters is RecordingUniversalFilters => {
    return 'filter_group' in filters
}

export const filtersFromUniversalFilterGroups = (filters: RecordingUniversalFilters): UniversalFilterValue[] => {
    const group = filters.filter_group.values[0] as UniversalFiltersGroup
    return group.values as UniversalFilterValue[]
}
