import { ViewMadeBy } from 'scenes/views/viewFeed'
import { VIEW_TYPES, ViewItem, ViewTypeFilter } from 'scenes/views/viewsUtils'

import { RECENT_CREATED_BY_OPTIONS, TodayRecentCreatedByFilter, TodayRecentPinnedFilter } from './todayRecentFilters'

export interface TodayViewsFilters {
    type: ViewTypeFilter
    createdBy: TodayRecentCreatedByFilter
    madeBy: ViewMadeBy
    pinned: TodayRecentPinnedFilter
}

export const DEFAULT_VIEWS_FILTERS: TodayViewsFilters = {
    type: 'all',
    createdBy: 'anyone',
    madeBy: 'anyone',
    pinned: 'any',
}

export const VIEWS_TYPE_OPTIONS: { value: ViewTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    ...VIEW_TYPES.map((info) => ({ value: info.type, label: info.pluralLabel })),
]

export const VIEWS_CREATED_BY_OPTIONS = RECENT_CREATED_BY_OPTIONS

export const VIEWS_MADE_BY_OPTIONS: { value: ViewMadeBy; label: string }[] = [
    { value: 'anyone', label: 'Anyone' },
    { value: 'people', label: 'People' },
    { value: 'agents', label: 'Agents' },
]

export const VIEWS_PINNED_OPTIONS: { value: TodayRecentPinnedFilter; label: string }[] = [
    { value: 'any', label: 'All views' },
    { value: 'pinned', label: 'Pinned only' },
]

/** Saved filters from before a filter existed lack it, so that filter starts at its default. */
export function withViewsFilterDefaults(saved: Partial<TodayViewsFilters>): TodayViewsFilters {
    return { ...DEFAULT_VIEWS_FILTERS, ...saved }
}

export function viewsFiltersActive(filters: TodayViewsFilters): boolean {
    return (Object.keys(DEFAULT_VIEWS_FILTERS) as (keyof TodayViewsFilters)[]).some(
        (key) => filters[key] !== DEFAULT_VIEWS_FILTERS[key]
    )
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
                (!!item.createdByUuid && (filters.createdBy === 'me') === (item.createdByUuid === currentUserUuid))) &&
            (filters.madeBy === 'anyone' || (filters.madeBy === 'agents') === !!item.alertInvestigation) &&
            (filters.pinned === 'any' || item.pinned)
    )
}
