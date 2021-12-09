import { kea } from 'kea'
import api from 'lib/api'
import { GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModelType } from './groupsModelType'
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
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${groupType.group_type_index}` as TaxonomicFilterGroupType
                )
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupTypes,
    }),
})
