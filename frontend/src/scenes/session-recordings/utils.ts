import { RecordingFilters, RecordingUniversalFilters } from '~/types'

export function isUniversalFilters(
    filters: RecordingFilters | RecordingUniversalFilters
): filters is RecordingUniversalFilters {
    return 'filter_group' in filters
}
