import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import type { personsAndGroupsSidebarLogicType } from './personsAndGroupsType'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '../navigationLogic'
import { SidebarCategory, BasicListItem } from '../types'
import { urls } from '@posthog/apps-common'
import { findSearchTermInItemName } from './utils'
import { groupsModel } from '~/models/groupsModel'
import { capitalizeFirstLetter } from 'lib/utils'
import { GroupsPaginatedResponse, groupsListLogic } from 'scenes/groups/groupsListLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'

export const personsAndGroupsSidebarLogic = kea<personsAndGroupsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'personsAndGroupsSidebarLogic']),
    connect(() => ({
        values: [
            groupsModel,
            ['groupTypes'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
            navigation3000Logic,
            ['searchTerm'],
        ],
    })),
    selectors(({ values }) => ({
        contents: [
            (s) => [s.groupTypes, s.groups, s.groupsLoading],
            (groupTypes, groups, groupsLoading): SidebarCategory[] => {
                return [
                    ...groupTypes.map(
                        (groupType) =>
                            ({
                                key: `groups-${groupType.group_type_index}`,
                                title: capitalizeFirstLetter(groupType.name_plural || `${groupType.group_type} groups`),
                                items: groups[groupType.group_type_index].results.map((group) => {
                                    const { searchTerm } = values
                                    const displayId = groupDisplayId(group.group_key, group.group_properties)
                                    return {
                                        key: group.group_key,
                                        name: displayId,
                                        url: urls.group(groupType.group_type_index, group.group_key),
                                        searchMatch: findSearchTermInItemName(displayId, searchTerm),
                                    } as BasicListItem
                                }),
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
                        if (s.groupTypes(state).length > groupTypeIndex) {
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
                        if (s.groupTypes(state).length > groupTypeIndex) {
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
    subscriptions(({ values }) => ({
        searchTerm: (searchTerm) => {
            for (const { group_type_index: groupTypeIndex } of values.groupTypes) {
                groupsListLogic({ groupTypeIndex }).actions.setSearch(searchTerm, false)
            }
        },
    })),
])
