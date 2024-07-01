import { UniversalFiltersGroup, UniversalFilterValue } from 'lib/components/UniversalFilters/UniversalFilters'

import { RecordingUniversalFilters } from '~/types'

export const filtersFromUniversalFilterGroups = (filters: RecordingUniversalFilters): UniversalFilterValue[] => {
    const group = filters.filter_group.values[0] as UniversalFiltersGroup
    return group.values as UniversalFilterValue[]
}
