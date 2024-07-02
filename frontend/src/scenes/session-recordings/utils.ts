import { UniversalFiltersGroup, UniversalFilterValue } from 'lib/components/UniversalFilters/UniversalFilters'

import { RecordingFilters, RecordingUniversalFilters } from '~/types'

export const isUniversalFilters = (
    filters: RecordingUniversalFilters | RecordingFilters
): filters is RecordingUniversalFilters => {
    return 'filter_group' in filters
}

export const filtersFromUniversalFilterGroups = (filters: RecordingUniversalFilters): UniversalFilterValue[] => {
    const group = filters.filter_group.values[0] as UniversalFiltersGroup
    return group.values as UniversalFilterValue[]
}
