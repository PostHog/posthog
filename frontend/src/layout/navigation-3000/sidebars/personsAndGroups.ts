import { urls } from '@posthog/apps-common'
import { afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { combineUrl } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { groupsListLogic, GroupsPaginatedResponse } from 'scenes/groups/groupsListLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { asDisplay, asLink } from 'scenes/persons/person-utils'
import { personsLogic } from 'scenes/persons/personsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { PersonType } from '~/types'

import { navigation3000Logic } from '../navigationLogic'
import { BasicListItem, SidebarCategory } from '../types'
import type { personsAndGroupsSidebarLogicType } from './personsAndGroupsType'
import { findSearchTermInItemName } from './utils'

export const personsAndGroupsSidebarLogic = kea<personsAndGroupsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'personsAndGroupsSidebarLogic']),
    connect(() => ({
        values: [
            personsLogic,
            ['persons', 'personsLoading'],
            groupsModel,
            ['groupTypes'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
            navigation3000Logic,
            ['searchTerm'],
        ],
        actions: [personsLogic, ['setListFilters as setPersonsListFilters', 'loadPersons']],
    })),
    reducers(() => ({
        infinitePersons: [
            [] as (PersonType | undefined)[],
            {
                [personsLogic.actionTypes.loadPersonsSuccess]: (state, { persons }) => {
                    // Reset array if offset is 0
                    const items: (PersonType | undefined)[] = persons.offset === 0 ? [] : state.slice()
                    for (let i = 0; i < persons.results.length; i++) {
                        items[persons.offset + i] = persons.results[i]
                    }
                    return items
                },
            },
        ],
    })),
    selectors(({ values, cache }) => ({
        contents: [
            (s) => [s.persons, s.infinitePersons, s.personsLoading, s.groupTypes, s.groups, s.groupsLoading],
            (persons, infinitePersons, personsLoading, groupTypes, groups, groupsLoading): SidebarCategory[] => {
                return [
                    {
                        key: 'persons',
                        noun: 'person',
                        items: infinitePersons.map((person) => {
                            if (!person) {
                                return person
                            }
                            const name = asDisplay(person)
                            // It is not typical to use `values` in a selector instead of a selector dependency,
                            // but this is intentional: we only want to take the new search term into account AFTER
                            // person results using it have been loaded.
                            const { searchTerm } = values
                            return {
                                key: person.distinct_ids,
                                name: asDisplay(person),
                                url: asLink(person),
                                searchMatch: findSearchTermInItemName(name, searchTerm),
                            } as BasicListItem
                        }),
                        loading: personsLoading,
                        remote: {
                            isItemLoaded: (index) => !!(cache.requestedPersons[index] || infinitePersons[index]),
                            loadMoreItems: async (startIndex, stopIndex) => {
                                let moreUrl = persons.next || persons.previous
                                if (!moreUrl) {
                                    throw new Error('No URL for loading more persons is known')
                                }
                                for (let i = startIndex; i <= stopIndex; i++) {
                                    cache.requestedPersons[i] = true
                                }
                                moreUrl = combineUrl(moreUrl, {
                                    offset: startIndex,
                                    limit: stopIndex - startIndex + 1,
                                }).url
                                await personsLogic.asyncActions.loadPersons(moreUrl)
                            },
                            itemCount: persons.count,
                            minimumBatchSize: 100,
                        },
                    } as SidebarCategory,
                    ...Array.from(groupTypes.values()).map(
                        (groupType) =>
                            ({
                                key: `groups-${groupType.group_type_index}`,
                                noun: [
                                    groupType.name_singular || `${groupType.group_type} group`,
                                    groupType.name_plural || `${groupType.group_type} groups`,
                                ],
                                items:
                                    groups[groupType.group_type_index]?.results.map((group) => {
                                        const { searchTerm } = values
                                        const displayId = groupDisplayId(group.group_key, group.group_properties)
                                        return {
                                            key: group.group_key,
                                            name: displayId,
                                            url: urls.group(groupType.group_type_index, group.group_key),
                                            searchMatch: findSearchTermInItemName(displayId, searchTerm),
                                        } as BasicListItem
                                    }) || [],
                                loading: groupsLoading[groupType.group_type_index],
                                // FIXME: Add remote
                            } as SidebarCategory)
                    ),
                ]
            },
        ],
        groups: [
            (s) =>
                Array(5)
                    .fill(null)
                    .map((_, groupTypeIndex) => (state) => {
                        if (s.groupTypes(state)[groupTypeIndex]) {
                            groupsListLogic({ groupTypeIndex }).mount()
                            return groupsListLogic({ groupTypeIndex }).selectors.groups(state)
                        }
                    }),
            (
                groups0: GroupsPaginatedResponse,
                groups1: GroupsPaginatedResponse,
                groups2: GroupsPaginatedResponse,
                groups3: GroupsPaginatedResponse,
                groups4: GroupsPaginatedResponse
            ) => {
                return [groups0, groups1, groups2, groups3, groups4]
            },
        ],
        groupsLoading: [
            (s) =>
                Array(5)
                    .fill(null)
                    .map((_, groupTypeIndex) => (state) => {
                        if (s.groupTypes(state)[groupTypeIndex]) {
                            groupsListLogic({ groupTypeIndex }).mount()
                            return groupsListLogic({ groupTypeIndex }).selectors.groupsLoading(state)
                        }
                    }),
            (
                groupsLoading0: boolean,
                groupsLoading1: boolean,
                groupsLoading2: boolean,
                groupsLoading3: boolean,
                groupsLoading4: boolean
            ) => {
                return [groupsLoading0, groupsLoading1, groupsLoading2, groupsLoading3, groupsLoading4]
            },
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, string] | null => {
                if (activeScene === Scene.Person) {
                    const { _: personDistinctId } = sceneParams.params
                    return personDistinctId ? ['persons', personDistinctId as string] : null
                }
                if (activeScene === Scene.Group) {
                    const { groupKey, groupTypeIndex } = sceneParams.params
                    return groupKey ? [`groups-${groupTypeIndex}`, decodeURIComponent(groupKey as string)] : null
                }
                return null
            },
        ],
        // kea-typegen doesn't like selectors without deps, so searchTerm is just for appearances
        debounceSearch: [(s) => [s.searchTerm], () => true],
    })),
    listeners(({ cache }) => ({
        loadPersons: async ({ url }) => {
            const offset = url ? parseInt(new URL(url).searchParams.get('offset') || '0') : 0
            if (offset === 0) {
                cache.requestedPersons = []
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        searchTerm: (searchTerm) => {
            actions.setPersonsListFilters({ search: searchTerm })
            actions.loadPersons()
            for (const { group_type_index: groupTypeIndex } of Object.values(values.groupTypes)) {
                groupsListLogic({ groupTypeIndex }).actions.setSearch(searchTerm, false)
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        cache.requestedPersons = []
        actions.loadPersons()
    }),
])
