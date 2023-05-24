import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import type { personsAndGroupsSidebarLogicType } from './personsAndGroupsSidebarLogicType'
import { personsLogic } from 'scenes/persons/personsLogic'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '../navigationLogic'
import { Accordion, BasicListItem } from '../types'
import { asDisplay, asLink, urls } from '@posthog/apps-common'
import { findSearchTermInItemName } from './utils'
import { groupsModel } from '~/models/groupsModel'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsListLogic } from 'scenes/groups/groupsListLogic'

const SEARCH_DEBOUNCE_MS = 200

export const personsAndGroupsSidebarLogic = kea<personsAndGroupsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'personsAndGroupsSidebarLogic']),
    connect({
        values: [
            personsLogic,
            ['persons', 'personsLoading'],
            groupsModel,
            ['groupTypes'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
        ],
        actions: [personsLogic, ['setListFilters', 'loadPersons']],
    }),
    actions({
        loadData: true,
    }),
    listeners({
        loadData: () => {
            personsLogic.actions.loadPersons()
        },
    }),
    selectors(({ actions, values }) => ({
        isLoading: [(s) => [s.personsLoading], (personsLoading) => personsLoading],
        contents: [
            (s) => [
                s.persons,
                s.personsLoading,
                s.groupTypes,
                groupsListLogic({ groupTypeIndex: 0 }).selectors.groups,
                groupsListLogic({ groupTypeIndex: 0 }).selectors.groupsLoading,
                groupsListLogic({ groupTypeIndex: 1 }).selectors.groups,
                groupsListLogic({ groupTypeIndex: 1 }).selectors.groupsLoading,
                groupsListLogic({ groupTypeIndex: 2 }).selectors.groups,
                groupsListLogic({ groupTypeIndex: 2 }).selectors.groupsLoading,
                groupsListLogic({ groupTypeIndex: 3 }).selectors.groups,
                groupsListLogic({ groupTypeIndex: 3 }).selectors.groupsLoading,
                groupsListLogic({ groupTypeIndex: 4 }).selectors.groups,
                groupsListLogic({ groupTypeIndex: 4 }).selectors.groupsLoading,
            ],
            (
                persons,
                personsLoading,
                groupTypes,
                groups0,
                groupsLoading0,
                groups1,
                groupsLoading1,
                groups2,
                groupsLoading2,
                groups3,
                groupsLoading3,
                groups4,
                groupsLoading4
            ): Accordion[] => {
                const groups = [groups0, groups1, groups2, groups3, groups4]
                const groupsLoading = [groupsLoading0, groupsLoading1, groupsLoading2, groupsLoading3, groupsLoading4]
                return [
                    {
                        key: 'persons',
                        title: 'Persons',
                        items: persons.results.map((person) => {
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
                        loadMore: persons.next ? () => actions.loadPersons(persons.next) : undefined,
                    } as Accordion,
                    ...groupTypes.map(
                        (groupType) =>
                            ({
                                key: `groups-${groupType.group_type_index}`,
                                title: capitalizeFirstLetter(groupType.name_plural || `${groupType.group_type} groups`),
                                items: groups[groupType.group_type_index].results.map((group) => {
                                    const { searchTerm } = values
                                    return {
                                        key: group.group_key,
                                        name: group.group_key,
                                        url: urls.group(groupType.group_type_index, group.group_key),
                                        searchMatch: findSearchTermInItemName(group.group_key, searchTerm),
                                    } as BasicListItem
                                }),
                                loading: groupsLoading[groupType.group_type_index],
                            } as Accordion)
                    ),
                ]
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
                    return groupKey ? [`groups-${groupTypeIndex}`, groupKey as string] : null
                }
                return null
            },
        ],
        searchTerm: [() => [navigation3000Logic.selectors.searchTerm], (searchTerm) => searchTerm],
    })),
    subscriptions(({ actions, cache }) => ({
        searchTerm: (searchTerm) => {
            clearTimeout(cache.loadTimeout)
            actions.setListFilters({ search: searchTerm })
            cache.loadTimeout = setTimeout(() => actions.loadData(), SEARCH_DEBOUNCE_MS)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
