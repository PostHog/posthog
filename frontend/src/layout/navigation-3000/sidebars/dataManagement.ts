import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getFilterLabel } from 'lib/taxonomy'
import { actionsFuse, actionsLogic } from 'scenes/actions/actionsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { ActionType, EventDefinition, FilterLogicalOperator, PropertyDefinition, ReplayTabs } from '~/types'

import { BasicListItem, SidebarCategory } from '../types'
import type { dataManagementSidebarLogicType } from './dataManagementType'
import { findSearchTermInItemName } from './utils'
import { FuseSearchMatch } from './utils'

export const dataManagementSidebarLogic = kea<dataManagementSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'dataManagementSidebarLogic']),
    connect(() => ({
        values: [
            sceneLogic,
            ['activeScene', 'sceneParams'],
            navigation3000Logic,
            ['searchTerm'],
            actionsLogic,
            ['actions', 'actionsLoading'],
        ],
    })),
    actions({
        loadEventDefinitions: (startIndex: number, stopIndex: number) => ({ startIndex, stopIndex }),
        loadPropertyDefinitions: (startIndex: number, stopIndex: number) => ({ startIndex, stopIndex }),
    }),
    loaders(({ values, cache }) => ({
        infiniteEventDefinitions: [
            [[], 0] as [(EventDefinition | null)[], number],
            {
                loadEventDefinitions: async ({ startIndex, stopIndex }) => {
                    if (!startIndex) {
                        cache.requestedEventDefinitions = []
                    }
                    for (let i = startIndex; i < stopIndex; i++) {
                        cache.requestedEventDefinitions[i] = true
                    }
                    const results = await api.eventDefinitions.list({
                        offset: startIndex,
                        limit: stopIndex - startIndex,
                        search: values.searchTerm,
                    })
                    const newItems = startIndex ? values.infiniteEventDefinitions[0].slice() : []
                    for (let i = 0; i < results.results.length; i++) {
                        newItems[startIndex + i] = results.results[i]
                    }
                    return [newItems, results.count]
                },
            },
        ],
        infinitePropertyDefinitions: [
            [[], 0] as [(PropertyDefinition | null)[], number],
            {
                loadPropertyDefinitions: async ({ startIndex, stopIndex }) => {
                    if (!startIndex) {
                        cache.requestedPropertyDefinitions = []
                    }
                    for (let i = startIndex; i < stopIndex; i++) {
                        cache.requestedPropertyDefinitions[i] = true
                    }
                    const results = await api.propertyDefinitions.list({
                        offset: startIndex,
                        limit: stopIndex - startIndex,
                        search: values.searchTerm,
                    })
                    const newItems = startIndex ? values.infinitePropertyDefinitions[0].slice() : []
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
            (s) => [
                s.infiniteEventDefinitions,
                s.infiniteEventDefinitionsLoading,
                s.infinitePropertyDefinitions,
                s.infinitePropertyDefinitionsLoading,
                s.relevantActions,
                s.actionsLoading,
            ],
            (
                [eventDefinitions, eventDefinitionCount],
                infiniteEventDefinitionsLoading,
                [propertyDefinitions, propertyDefinitionCount],
                infinitePropertyDefinitionsLoading,
                relevantActions,
                actionsLoading
            ) => [
                {
                    key: 'event-definitions',
                    noun: 'event definition',
                    loading: infiniteEventDefinitionsLoading,
                    items: eventDefinitions.map(
                        (eventDefinition) =>
                            eventDefinition &&
                            ({
                                key: eventDefinition.id,
                                name: getFilterLabel(eventDefinition.name, TaxonomicFilterGroupType.Events),
                                url: urls.eventDefinition(eventDefinition.id),
                                searchMatch: findSearchTermInItemName(
                                    getFilterLabel(eventDefinition.name, TaxonomicFilterGroupType.Events),
                                    values.searchTerm
                                ),
                                menuItems: [
                                    {
                                        label: 'View recordings',
                                        to: urls.replay(ReplayTabs.Home, {
                                            filter_group: {
                                                type: FilterLogicalOperator.And,
                                                values: [
                                                    {
                                                        type: FilterLogicalOperator.And,
                                                        values: [
                                                            {
                                                                id: eventDefinition.name,
                                                                type: 'events',
                                                                order: 0,
                                                                name: eventDefinition.name,
                                                            },
                                                        ],
                                                    },
                                                ],
                                            },
                                        }),
                                    },
                                ],
                            } as BasicListItem)
                    ),
                    remote: {
                        isItemLoaded: (index) => !!(cache.requestedEventDefinitions[index] || eventDefinitions[index]),
                        loadMoreItems: (startIndex, stopIndex) => actions.loadEventDefinitions(startIndex, stopIndex),
                        itemCount: eventDefinitionCount,
                    },
                } as SidebarCategory,
                {
                    key: 'property-definitions',
                    noun: 'property definition',
                    loading: infinitePropertyDefinitionsLoading,
                    items: propertyDefinitions.map(
                        (propertyDefinition) =>
                            propertyDefinition &&
                            ({
                                key: propertyDefinition.id,
                                name: getFilterLabel(propertyDefinition.name, TaxonomicFilterGroupType.EventProperties),
                                url: urls.propertyDefinition(propertyDefinition.id),
                                searchMatch: findSearchTermInItemName(
                                    getFilterLabel(propertyDefinition.name, TaxonomicFilterGroupType.EventProperties),
                                    values.searchTerm
                                ),
                            } as BasicListItem)
                    ),
                    remote: {
                        isItemLoaded: (index) =>
                            !!(cache.requestedPropertyDefinitions[index] || propertyDefinitions[index]),
                        loadMoreItems: (startIndex, stopIndex) =>
                            actions.loadPropertyDefinitions(startIndex, stopIndex),
                        itemCount: propertyDefinitionCount,
                    },
                } as SidebarCategory,
                {
                    key: 'actions',
                    noun: 'action',
                    loading: actionsLoading,
                    onAdd: urls.action('new'), // TODO: Show "New button" at accordion level
                    items: relevantActions.map(([action, matches]) => ({
                        key: action.id,
                        name: action.name,
                        url: urls.action(action.id),
                        searchMatch: matches
                            ? {
                                  matchingFields: matches.map((match) => match.key),
                                  nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                              }
                            : null,
                    })),
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, string] | null => {
                if (activeScene === Scene.EventDefinition) {
                    return ['event-definitions', sceneParams.params.id]
                }
                if (activeScene === Scene.PropertyDefinition) {
                    return ['property-definitions', sceneParams.params.id]
                }
                if (activeScene === Scene.Action) {
                    return ['actions', sceneParams.params.id]
                }
                return null
            },
        ],
        // kea-typegen doesn't like selectors without deps, so searchTerm is just for appearances
        debounceSearch: [(s) => [s.searchTerm], () => true],
        relevantActions: [
            (s) => [s.actions, navigation3000Logic.selectors.searchTerm],
            (actions, searchTerm): [ActionType, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return actionsFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return actions.map((action) => [action, null])
            },
        ],
    })),
    subscriptions(({ actions }) => ({
        searchTerm: () => {
            actions.loadEventDefinitions(0, 100)
            actions.loadPropertyDefinitions(0, 100)
        },
    })),
    afterMount(({ actions, cache }) => {
        cache.requestedEventDefinitions = []
        cache.requestedPropertyDefinitions = []
        actions.loadEventDefinitions(0, 100)
        actions.loadPropertyDefinitions(0, 100)
    }),
])
