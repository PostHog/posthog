import { LegacyRecordingFilters, RecordingUniversalFilters, UniversalFiltersGroup, UniversalFilterValue } from '~/types'

export const TimestampFormatToLabel = {
    relative: 'Relative',
    utc: 'UTC',
    device: 'Device',
}

export const isUniversalFilters = (
    filters: RecordingUniversalFilters | LegacyRecordingFilters
): filters is RecordingUniversalFilters => {
    return 'filter_group' in filters
}

const isUniversalFiltersGroup = (group: unknown): group is UniversalFiltersGroup => {
    return !!group && typeof group === 'object' && 'values' in group && 'type' in group
}

// TODO we shouldn't be ever converting to filters any more, but I won't unpick this in this PR
export const filtersFromUniversalFilterGroups = (filters: RecordingUniversalFilters): UniversalFilterValue[] => {
    const filterGroupValues = filters.filter_group.values
    if (isUniversalFiltersGroup(filterGroupValues)) {
        return filterGroupValues.values[0] as UniversalFilterValue[]
    }
    return filterGroupValues as UniversalFilterValue[]
}
