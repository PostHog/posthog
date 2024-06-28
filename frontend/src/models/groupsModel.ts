import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { GroupType, GroupTypeIndex } from '~/types'

import type { groupsModelType } from './groupsModelType'

export interface Noun {
    singular: string
    plural: string
}

export const groupsModel = kea<groupsModelType>([
    path(['models', 'groupsModel']),
    connect({
        values: [teamLogic, ['currentTeamId'], groupsAccessLogic, ['groupsEnabled', 'groupsAccessStatus']],
    }),
    loaders(({ values }) => ({
        groupTypesRaw: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    return await api.get(`api/projects/${values.currentTeamId}/groups_types`)
                },
                updateGroupTypesMetadata: async (payload: Array<GroupType>) => {
                    if (values.groupsEnabled) {
                        return await api.update(
                            `/api/projects/${teamLogic.values.currentTeamId}/groups_types/update_metadata`,
                            payload
                        )
                    }
                    return []
                },
            },
        ],
    })),
    selectors({
        groupTypes: [
            (s) => [s.groupTypesRaw],
            (groupTypesRaw) =>
                new Map<GroupTypeIndex, GroupType>(
                    groupTypesRaw.map((groupType) => [groupType.group_type_index, groupType])
                ),
        ],
        groupTypesLoading: [(s) => [s.groupTypesRawLoading], (groupTypesRawLoading) => groupTypesRawLoading],

        showGroupsOptions: [
            (s) => [s.groupsAccessStatus, s.groupsEnabled, s.groupTypes],
            (status, enabled, groupTypes) =>
                status !== GroupsAccessStatus.Hidden || (enabled && Array.from(groupTypes.values()).length > 0),
        ],
        groupsTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return Array.from(groupTypes.values()).map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${groupType.group_type_index}` as unknown as TaxonomicFilterGroupType
                )
            },
        ],
        groupNamesTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return Array.from(groupTypes.values()).map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupNamesPrefix}_${groupType.group_type_index}` as unknown as TaxonomicFilterGroupType
                )
            },
        ],
        aggregationLabel: [
            (s) => [s.groupTypes],
            (groupTypes) =>
                (groupTypeIndex: number | null | undefined, deferToUserWording: boolean = false): Noun => {
                    if (groupTypeIndex != undefined) {
                        const groupType = groupTypes.get(groupTypeIndex as GroupTypeIndex)
                        if (groupType) {
                            return {
                                singular: groupType.name_singular || groupType.group_type,
                                plural: groupType.name_plural || `${groupType.group_type}(s)`,
                            }
                        }
                        return {
                            singular: 'unknown group',
                            plural: 'unknown groups',
                        }
                    }
                    return deferToUserWording
                        ? {
                              singular: 'user',
                              plural: 'users',
                          }
                        : { singular: 'person', plural: 'persons' }
                },
        ],
    }),
    subscriptions(({ values }) => ({
        groupsEnabled: (enabled) => {
            // Load the groups types in the case of groups becoming an available feature after this logic is mounted
            if (!values.groupTypesLoading && enabled) {
                groupsModel.actions.loadAllGroupTypes()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAllGroupTypes()
    }),
])
