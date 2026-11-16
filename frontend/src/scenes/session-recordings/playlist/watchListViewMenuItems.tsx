import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { RecordingUniversalFilters } from '~/types'

import {
    useAutoplayMenuItems,
    useHideRecordingsMenuItems,
    useLayoutMenuItems,
    useTimestampFormatMenuItems,
} from './listViewMenuItems'
import {
    RecordingSort,
    preferredRecordingsSortStorage,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'
import { getRecommendedFilterChange, getSortChangedEvent } from './SessionRecordingsPlaylistSettings'

// A list already sorted by an order outside this set keeps it until the sort changes.
const WATCH_SORTS: { label: string; order: NonNullable<RecordingUniversalFilters['order']> }[] = [
    { label: 'Latest', order: 'start_time' },
    { label: 'Activity', order: 'activity_score' },
    { label: 'Duration', order: 'duration' },
    { label: 'Errors', order: 'console_error_count' },
]

export function watchSortLabel(order: RecordingUniversalFilters['order']): string {
    if (order === 'surfacing_score') {
        return 'Relevance'
    }
    return WATCH_SORTS.find((sort) => sort.order === (order ?? 'start_time'))?.label ?? 'Sorted'
}

export function useWatchViewMenuItems(
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
): LemonMenuItems {
    const { canSortByRelevance, canFilterByRelevance, listSort } = useValues(sessionRecordingsPlaylistLogic)
    const hideItems = useHideRecordingsMenuItems()
    const current = { ...filters, ...listSort }
    const order = current.order ?? 'start_time'
    const direction = current.order_direction ?? 'DESC'

    const changeSort = (sort: RecordingSort): void => {
        const event = getSortChangedEvent(current, sort)
        if (event) {
            posthog.capture('session recording list sort changed', event)
        }
        preferredRecordingsSortStorage.set(sort)
        setFilters(sort)
    }

    const sortItems: LemonMenuItem[] = [
        ...(canSortByRelevance
            ? [
                  {
                      label: 'Relevance',
                      onClick: () => changeSort({ order: 'surfacing_score', order_direction: 'DESC' }),
                      active: order === 'surfacing_score',
                      'data-attr': 'list-sort-surfacing-score',
                  },
              ]
            : []),
        ...WATCH_SORTS.map((sort) => ({
            label: sort.label,
            onClick: () => changeSort({ order: sort.order, order_direction: 'DESC' }),
            active: order === sort.order,
            'data-attr': `list-sort-${sort.order.replace(/_/g, '-')}`,
        })),
    ]
    const directionItems: LemonMenuItem[] = [
        {
            label: order === 'start_time' ? 'Newest first' : 'Highest first',
            onClick: () => changeSort({ order, order_direction: 'DESC' }),
            active: direction === 'DESC',
            'data-attr': 'list-sort-direction-desc',
        },
        {
            label: order === 'start_time' ? 'Oldest first' : 'Lowest first',
            onClick: () => changeSort({ order, order_direction: 'ASC' }),
            active: direction === 'ASC',
            'data-attr': 'list-sort-direction-asc',
        },
    ]
    const showItems: LemonMenuItem[] = [
        ...(canFilterByRelevance
            ? [
                  {
                      label: 'High relevance only',
                      active: !!filters.recommended_only,
                      onClick: () => {
                          posthog.capture('session recording recommended filter changed', {
                              enabled: !filters.recommended_only,
                          })
                          setFilters(getRecommendedFilterChange(!filters.recommended_only))
                      },
                      'data-attr': 'session-recordings-recommended-only',
                  },
              ]
            : []),
        ...hideItems,
    ]

    return [{ title: 'Sort by', items: sortItems }, { items: directionItems }, { title: 'Show', items: showItems }]
}

export function useWatchSettingsMenuItems(): LemonMenuItems {
    const timestampItems = useTimestampFormatMenuItems()
    const autoplayItems = useAutoplayMenuItems()
    const layoutItems = useLayoutMenuItems()
    return [
        { title: 'Timestamps', items: timestampItems },
        { title: 'Autoplay', items: autoplayItems },
        ...(layoutItems.length ? [{ title: 'Layout', items: layoutItems }] : []),
    ]
}
