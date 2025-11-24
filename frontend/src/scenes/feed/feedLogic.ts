import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

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
            ['all'] as string[],
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
                // Filter items based on search query (name, author, description only - NOT type)
                let filteredItems = searchQuery
                    ? items.filter((item) => {
                          const query = searchQuery.toLowerCase()
                          return (
                              item.name?.toLowerCase().includes(query) ||
                              item.created_by?.toLowerCase().includes(query) ||
                              item.description?.toLowerCase().includes(query)
                          )
                      })
                    : items

                // Filter by selected types (if not "all")
                if (selectedTypes.length > 0 && !selectedTypes.includes('all')) {
                    filteredItems = filteredItems.filter((item) => selectedTypes.includes(item.type))
                }

                // Separate upcoming/warning items from regular activity items
                const upcomingItems: FeedItem[] = []
                const regularItems: FeedItem[] = []

                filteredItems.forEach((item) => {
                    // Warning/upcoming item types go to UPCOMING section
                    if (item.type === 'expiring_recordings') {
                        upcomingItems.push(item)
                    } else {
                        regularItems.push(item)
                    }
                })

                // Group regular items by date - enumerate last 7 days, then "OLDER"
                const dateGroups: Record<string, FeedItem[]> = {}

                const now = new Date()
                const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())

                regularItems.forEach((item) => {
                    const itemDate = new Date(item.created_at)
                    const itemDay = new Date(itemDate.getFullYear(), itemDate.getMonth(), itemDate.getDate())
                    const dayDiff = Math.floor((today.getTime() - itemDay.getTime()) / (1000 * 60 * 60 * 24))

                    let groupKey: string

                    if (dayDiff === 0) {
                        groupKey = 'TODAY'
                    } else if (dayDiff === 1) {
                        groupKey = 'YESTERDAY'
                    } else if (dayDiff >= 2 && dayDiff <= 6) {
                        // Format: "Tuesday, Nov 25" for days 2-6
                        const dayName = itemDay.toLocaleDateString('en-US', { weekday: 'long' })
                        const monthDay = itemDay.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                        groupKey = `${dayName}, ${monthDay}`
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

                // Add UPCOMING section if there are upcoming items
                if (upcomingItems.length > 0) {
                    const upcomingTypeGroups: Record<string, FeedItem[]> = {}
                    upcomingItems.forEach((item) => {
                        if (!upcomingTypeGroups[item.type]) {
                            upcomingTypeGroups[item.type] = []
                        }
                        upcomingTypeGroups[item.type].push(item)
                    })
                    result.UPCOMING = upcomingTypeGroups
                }

                // Add regular date-based groups
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
