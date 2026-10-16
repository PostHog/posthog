import { VIEW_TYPES, ViewItem, ViewTypeFilter } from 'scenes/views/viewsUtils'

import { RECENT_CREATED_BY_OPTIONS, TodayRecentCreatedByFilter } from './todayRecentFilters'

export interface TodayViewsFilters {
    type: ViewTypeFilter
    createdBy: TodayRecentCreatedByFilter
}

export const DEFAULT_VIEWS_FILTERS: TodayViewsFilters = { type: 'all', createdBy: 'anyone' }

export const VIEWS_TYPE_OPTIONS: { value: ViewTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    ...VIEW_TYPES.map((info) => ({ value: info.type, label: info.pluralLabel })),
]

export const VIEWS_CREATED_BY_OPTIONS = RECENT_CREATED_BY_OPTIONS

export function viewsFiltersActive(filters: TodayViewsFilters): boolean {
    return filters.type !== DEFAULT_VIEWS_FILTERS.type || filters.createdBy !== DEFAULT_VIEWS_FILTERS.createdBy
}

/** The views that match the search and the filters, in their original order. */
export function filterRecentViews(
    items: ViewItem[],
    query: string,
    filters: TodayViewsFilters,
    currentUserUuid: string | null
): ViewItem[] {
    const needle = query.trim().toLowerCase()
    return items.filter(
        (item) =>
            (!needle || item.name.toLowerCase().includes(needle)) &&
            (filters.type === 'all' || item.type === filters.type) &&
            (filters.createdBy === 'anyone' ||
                // A view with no known creator is neither yours nor someone else's.
                (!!item.createdByUuid && (filters.createdBy === 'me') === (item.createdByUuid === currentUserUuid)))
    )
}
