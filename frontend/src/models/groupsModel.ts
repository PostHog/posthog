import { kea } from 'kea'
import api from 'lib/api'
import { GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import type { groupsModelType } from './groupsModelType'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

export const groupsModel = kea<groupsModelType>({
    path: ['models', 'groupsModel'],
    connect: {
        values: [teamLogic, ['currentTeamId'], groupsAccessLogic, ['groupsEnabled', 'groupsAccessStatus']],
    },
    loaders: ({ values }) => ({
        groupTypes: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    if (values.groupsEnabled) {
                        return await api.get(`api/projects/${values.currentTeamId}/groups_types`)
                    }
                    return []
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
    }),
    selectors: {
        showGroupsOptions: [
            (s) => [s.groupsAccessStatus, s.groupsEnabled, s.groupTypes],
            (status, enabled, groupTypes) => status !== GroupsAccessStatus.Hidden || (enabled && groupTypes.length > 0),
        ],
        groupsTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return groupTypes.map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${groupType.group_type_index}` as unknown as TaxonomicFilterGroupType
                )
            },
        ],
        groupNamesTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return groupTypes.map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupNamesPrefix}_${groupType.group_type_index}` as unknown as TaxonomicFilterGroupType
                )
            },
        ],
        aggregationLabel: [
            (s) => [s.groupTypes],
            (groupTypes) =>
                (groupTypeIndex: number | null | undefined, deferToUserWording: boolean = false) => {
                    if (groupTypeIndex != undefined && groupTypes.length > 0 && groupTypes[groupTypeIndex]) {
                        const groupType = groupTypes[groupTypeIndex]
                        return {
                            singular: groupType.name_plural || groupType.group_type,
                            plural: groupType.name_plural || `${groupType.group_type}(s)`,
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
    },
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupTypes,
    }),
})
