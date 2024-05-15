import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getFilterLabel } from 'lib/taxonomy'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { EventDefinition } from '~/types'

import { BasicListItem, SidebarCategory } from '../types'
import type { eventsManagementSidebarLogicType } from './eventsManagementType'
import { findSearchTermInItemName } from './utils'
import { sceneLogic } from 'scenes/sceneLogic'

export const eventsManagementSidebarLogic = kea<eventsManagementSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'eventsManagementSidebarLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeScene', 'sceneParams'], navigation3000Logic, ['searchTerm']],
    })),
    actions({
        loadEvents: (startIndex: number, stopIndex: number) => ({ startIndex, stopIndex }),
    }),
    loaders(({ values, cache }) => ({
        events: [
            [[], 0] as [(EventDefinition | null)[], number],
            {
                loadEvents: async ({ startIndex, stopIndex }) => {
                    if (!startIndex) {
                        cache.requestedEvents = []
                    }
                    for (let i = startIndex; i < stopIndex; i++) {
                        cache.requestedEvents[i] = true
                    }
                    const results = await api.events.list({
                        offset: startIndex,
                        limit: stopIndex - startIndex,
                        search: values.searchTerm,
                    })
                    const newItems = startIndex ? values.events[0].slice() : []
                    for (let i = 0; i < results.results.length; i++) {
                        newItems[startIndex + i] = results.results[i]
                    }
                    return [newItems, results.count]
                },
            },
        ],
    })),
    selectors(({ actions, values, cache }) => ({
        contents: [
            (s) => [s.events, s.eventsLoading],
            ([events, eventsCount], eventsLoading) => [
                {
                    key: 'events',
                    noun: 'events',
                    loading: eventsLoading,
                    items: events.map(
                        (event) =>
                            event &&
                            ({
                                key: event.id,
                                name: getFilterLabel(event.name, TaxonomicFilterGroupType.Events),
                                url: urls.event(event.id, event.timestamp),
                                searchMatch: findSearchTermInItemName(
                                    getFilterLabel(event.name, TaxonomicFilterGroupType.Events),
                                    values.searchTerm
                                ),
                            } as BasicListItem)
                    ),
                    remote: {
                        isItemLoaded: (index) => !!(cache.requestedEvents[index] || events[index]),
                        loadMoreItems: (startIndex, stopIndex) => actions.loadEvents(startIndex, stopIndex),
                        itemCount: eventsCount,
                    },
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, string] | null => {
                if (activeScene === Scene.Events) {
                    return ['events', sceneParams.params.id]
                }
                if (activeScene === Scene.LiveEvents) {
                    return ['live-events', sceneParams.params.id]
                }
                return null
            },
        ],
        // kea-typegen doesn't like selectors without deps, so searchTerm is just for appearances
        debounceSearch: [(s) => [s.searchTerm], () => true],
    })),
    subscriptions(({ actions }) => ({
        searchTerm: () => {
            actions.loadEvents(0, 100)
        },
    })),
    afterMount(({ actions, cache }) => {
        cache.requestedEvents = []
        actions.loadEvents(0, 100)
    }),
])
