import { isActionFilter, isEventFilter } from 'lib/components/UniversalFilters/utils'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

import { UniversalFilterValue } from '~/types'

export function summarizePlaylistEntityFilters(filters: UniversalFilterValue[]): string {
    return (
        [...filters.filter(isActionFilter), ...filters.filter(isEventFilter)]
            // A filter added from the replay filter bar has no `order`. Its comparison gives NaN, which sort reads as equal.
            .sort((a, b) => Number(a.order) - Number(b.order))
            .map((filter) => getDisplayNameFromEntityFilter(filter))
            .join(' & ')
    )
}
