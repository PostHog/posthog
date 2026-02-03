import { actions, kea, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType, TaxonomicFilterValue } from './types'

import type { recentItemsLogicType } from './recentItemsLogicType'

const MAX_RECENT_ITEMS = 20

export interface RecentItem {
    type: TaxonomicFilterGroupType
    value: TaxonomicFilterValue
    name: string
    timestamp: number
}

// Event-like group types that should be tracked in recent events
export const EVENT_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.CustomEvents,
    TaxonomicFilterGroupType.Actions,
]

// Property-like group types that should be tracked in recent properties
export const PROPERTY_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.SessionProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.NumericalEventProperties,
    TaxonomicFilterGroupType.EventMetadata,
]

export const recentItemsLogic = kea<recentItemsLogicType>([
    path(['lib', 'components', 'TaxonomicFilter', 'recentItemsLogic']),
    actions(() => ({
        addRecentEvent: (item: RecentItem) => ({ item }),
        addRecentProperty: (item: RecentItem) => ({ item }),
        clearRecentEvents: true,
        clearRecentProperties: true,
    })),
    reducers(() => ({
        recentEvents: [
            [] as RecentItem[],
            { persist: true },
            {
                addRecentEvent: (state, { item }) => {
                    // Remove duplicate if exists (by value and type)
                    const filtered = state.filter((i) => !(i.value === item.value && i.type === item.type))
                    // Add to front and limit size
                    return [item, ...filtered].slice(0, MAX_RECENT_ITEMS)
                },
                clearRecentEvents: () => [],
            },
        ],
        recentProperties: [
            [] as RecentItem[],
            { persist: true },
            {
                addRecentProperty: (state, { item }) => {
                    // Remove duplicate if exists (by value and type)
                    const filtered = state.filter((i) => !(i.value === item.value && i.type === item.type))
                    // Add to front and limit size
                    return [item, ...filtered].slice(0, MAX_RECENT_ITEMS)
                },
                clearRecentProperties: () => [],
            },
        ],
    })),
    selectors({
        recentEventOptions: [
            (s) => [s.recentEvents],
            (recentEvents): RecentItem[] => recentEvents,
        ],
        recentPropertyOptions: [
            (s) => [s.recentProperties],
            (recentProperties): RecentItem[] => recentProperties,
        ],
    }),
])
