import Fuse from 'fuse.js'
import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import type { feedLogicType } from './feedLogicType'

export interface FeedItem {
    id: string | number
    type: string
    name: string
    created_at: string
    description?: string
    created_by?: string
    additional_data?: Record<string, any>
}

export interface FeedFilters {
    days: number
}

export const feedLogic = kea<feedLogicType>([
    path(['scenes', 'feed', 'feedLogic']),
    actions({
        setFilters: (filters) => ({ filters }),
        setSearchQuery: (searchQuery) => ({ searchQuery }),
        setSelectedTypes: (selectedTypes) => ({ selectedTypes }),
        loadFeed: true,
    }),
    reducers({
        filters: [
            { days: 7 } as FeedFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
            },
        ],
        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        selectedTypes: [
            'all' as string,
            {
                setSelectedTypes: (_, { selectedTypes }) => selectedTypes,
            },
        ],
    }),
    loaders(({ values }) => ({
        feedItems: [
            [] as FeedItem[],
            {
                loadFeed: async () => {
                    try {
                        const response = await api.feed.recentUpdates(values.filters.days)
                        return response.results || []
                    } catch (error) {
                        console.error('[Feed] Error loading feed:', error)
                        return []
                    }
                },
            },
        ],
    })),
    selectors({
        groupedFeedItems: [
            (s) => [s.feedItems, s.searchQuery, s.selectedTypes],
            (items, searchQuery, selectedTypes): Record<string, Record<string, FeedItem[]>> => {
                let filteredItems = searchQuery
                    ? new Fuse<FeedItem>(items, {
                          keys: ['name', 'created_by', 'description'],
                          threshold: 0.3,
                          ignoreLocation: true,
                      })
                          .search(searchQuery)
                          .map((result) => result.item)
                    : items

                // Filter by selected types (if not "all")
                if (selectedTypes.length > 0 && !selectedTypes.includes('all')) {
                    filteredItems = filteredItems.filter((item: FeedItem) => selectedTypes.includes(item.type))
                }

                // Group items by date - enumerate last 7 days, then "OLDER"
                const dateGroups: Record<string, FeedItem[]> = {}

                const today = dayjs().startOf('day')

                filteredItems.forEach((item: FeedItem) => {
                    const itemDay = dayjs(item.created_at).startOf('day')
                    const dayDiff = today.diff(itemDay, 'days')

                    let groupKey: string

                    if (dayDiff === 0) {
                        groupKey = 'TODAY'
                    } else if (dayDiff === 1) {
                        groupKey = 'YESTERDAY'
                    } else if (dayDiff >= 2 && dayDiff <= 6) {
                        // Format: "Tuesday, Nov 25" for days 2-6
                        groupKey = itemDay.format('dddd, MMM D')
                    } else {
                        groupKey = 'OLDER'
                    }

                    if (!dateGroups[groupKey]) {
                        dateGroups[groupKey] = []
                    }
                    dateGroups[groupKey].push(item)
                })

                // Now group each date group by type
                const result: Record<string, Record<string, FeedItem[]>> = {}

                // Add date-based groups
                Object.entries(dateGroups).forEach(([dateKey, dateItems]) => {
                    if (dateItems.length === 0) {
                        return
                    }

                    const typeGroups: Record<string, FeedItem[]> = {}

                    dateItems.forEach((item) => {
                        if (!typeGroups[item.type]) {
                            typeGroups[item.type] = []
                        }
                        typeGroups[item.type].push(item)
                    })

                    result[dateKey] = typeGroups
                })

                return result
            },
        ],
    }),
])
