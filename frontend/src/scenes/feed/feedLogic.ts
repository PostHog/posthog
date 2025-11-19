import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { FeedActivityType, FeedItem, FeedPreferences, FeedResponse } from '~/types'

import type { feedLogicType } from './feedLogicType'

export interface FeedFilters {
    type?: FeedActivityType
    date_from?: string
    date_to?: string
}

export interface FeedLogicProps {
    key?: string
}

export const feedLogic = kea<feedLogicType>([
    path(['scenes', 'feed', 'feedLogic']),
    props({} as FeedLogicProps),
    key((props) => props.key || 'default'),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadFeed: (append: boolean = false) => ({ append }),
        setFilters: (filters: FeedFilters) => ({ filters }),
        resetFilters: true,
        loadPreferences: true,
        updatePreferences: (preferences: Partial<FeedPreferences>) => ({ preferences }),
        toggleActivityType: (type: FeedActivityType) => ({ type }),
        openPreferencesModal: true,
        closePreferencesModal: true,
    }),

    loaders(({ values, actions }) => ({
        feed: [
            null as FeedResponse | null,
            {
                loadFeed: async ({ append }, breakpoint) => {
                    const { currentTeamId } = values
                    if (!currentTeamId) {
                        return null
                    }

                    const offset = append ? (values.feed?.results.length ?? 0) : 0

                    const response = await api.feed.list({
                        ...values.filters,
                        offset,
                        limit: 20,
                    })

                    await breakpoint(100)

                    if (append && values.feed) {
                        return {
                            ...response,
                            results: [...values.feed.results, ...response.results],
                        }
                    }

                    return response
                },
            },
        ],

        preferences: [
            null as FeedPreferences | null,
            {
                loadPreferences: async (_, breakpoint) => {
                    const { currentTeamId } = values
                    if (!currentTeamId) {
                        return null
                    }

                    const response = await api.feed.getPreferences()
                    await breakpoint(100)
                    return response
                },

                updatePreferences: async ({ preferences }, breakpoint) => {
                    const { currentTeamId } = values
                    if (!currentTeamId) {
                        return values.preferences
                    }

                    const response = await api.feed.updatePreferences(preferences)
                    await breakpoint(100)

                    // Reload feed with new preferences
                    actions.loadFeed()

                    return response
                },
            },
        ],
    })),

    reducers({
        filters: [
            {} as FeedFilters,
            {
                setFilters: (_, { filters }) => filters,
                resetFilters: () => ({}),
            },
        ],

        preferencesModalOpen: [
            false,
            {
                openPreferencesModal: () => true,
                closePreferencesModal: () => false,
            },
        ],
    }),

    selectors({
        feedItems: [(s) => [s.feed], (feed): FeedItem[] => feed?.results ?? []],

        hasMore: [(s) => [s.feed], (feed): boolean => feed?.next !== null],

        groupedFeedItems: [
            (s) => [s.feedItems],
            (items): Record<string, Record<FeedActivityType, FeedItem[]>> => {
                // First group by date: Today, Yesterday, This week, Last week, Older
                const dateGroups: Record<string, FeedItem[]> = {
                    Today: [],
                    Yesterday: [],
                    'This week': [],
                    'Last week': [],
                    Older: [],
                }

                const now = new Date()
                const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
                const yesterday = new Date(today)
                yesterday.setDate(yesterday.getDate() - 1)
                const thisWeekStart = new Date(today)
                thisWeekStart.setDate(thisWeekStart.getDate() - today.getDay())
                const lastWeekStart = new Date(thisWeekStart)
                lastWeekStart.setDate(lastWeekStart.getDate() - 7)

                items.forEach((item) => {
                    const itemDate = new Date(item.created_at)
                    const itemDay = new Date(itemDate.getFullYear(), itemDate.getMonth(), itemDate.getDate())

                    if (itemDay.getTime() === today.getTime()) {
                        dateGroups.Today.push(item)
                    } else if (itemDay.getTime() === yesterday.getTime()) {
                        dateGroups.Yesterday.push(item)
                    } else if (itemDay >= thisWeekStart) {
                        dateGroups['This week'].push(item)
                    } else if (itemDay >= lastWeekStart) {
                        dateGroups['Last week'].push(item)
                    } else {
                        dateGroups.Older.push(item)
                    }
                })

                // Now group each date group by type
                const result: Record<string, Record<FeedActivityType, FeedItem[]>> = {}

                Object.entries(dateGroups).forEach(([dateKey, dateItems]) => {
                    if (dateItems.length === 0) {
                        return
                    }

                    const typeGroups: Record<FeedActivityType, FeedItem[]> = {} as Record<FeedActivityType, FeedItem[]>

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

        enabledActivityTypes: [
            (s) => [s.preferences],
            (preferences): FeedActivityType[] => {
                if (!preferences) {
                    return []
                }
                return Object.entries(preferences.enabled_types)
                    .filter(([_, enabled]) => enabled)
                    .map(([type, _]) => type as FeedActivityType)
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setFilters: () => {
            actions.loadFeed()
        },

        toggleActivityType: ({ type }) => {
            if (!values.preferences) {
                return
            }

            const currentlyEnabled = values.preferences.enabled_types[type]
            actions.updatePreferences({
                enabled_types: {
                    ...values.preferences.enabled_types,
                    [type]: !currentlyEnabled,
                },
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadFeed()
        actions.loadPreferences()
    }),
])
