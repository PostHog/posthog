import { afterMount, connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import type { personsAndGroupsSidebarLogicType } from './personsAndGroupsSidebarLogicType'
import { personsLogic } from 'scenes/persons/personsLogic'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '../navigationLogic'
import { Accordion, BasicListItem } from '../types'
import { asDisplay, asLink } from '@posthog/apps-common'
import { findSearchTermInItemName } from './utils'
import { groupsModel } from '~/models/groupsModel'
import { capitalizeFirstLetter } from 'lib/utils'

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
    selectors(({ actions, values }) => ({
        isLoading: [(s) => [s.personsLoading], (personsLoading) => personsLoading],
        contents: [
            (s) => [s.persons, s.personsLoading, s.groupTypes],
            (persons, personsLoading, groupTypes): Accordion[] => [
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
                            items: [],
                        } as Accordion)
                ),
            ],
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
            clearTimeout(cache.loadPersonsTimeout)
            actions.setListFilters({ search: searchTerm })
            cache.loadPersonsTimeout = setTimeout(() => actions.loadPersons(), SEARCH_DEBOUNCE_MS)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPersons()
    }),
])
