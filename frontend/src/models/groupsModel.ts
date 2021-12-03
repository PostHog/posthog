import { kea } from 'kea'
import api from 'lib/api'
import { AvailableFeature, GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsModelType } from './groupsModelType'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { userLogic } from 'scenes/userLogic'

export const groupsModel = kea<groupsModelType>({
    path: ['models', 'groupsModel'],
    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['clickhouseEnabled'],
            userLogic,
            ['hasAvailableFeature'],
        ],
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
        groupsEnabled: [
            (s) => [s.featureFlags, s.clickhouseEnabled, s.hasAvailableFeature],
            (featureFlags, clickhouseEnabled, hasAvailableFeature) =>
                featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS] &&
                clickhouseEnabled &&
                hasAvailableFeature(AvailableFeature.CORRELATION_ANALYSIS),
        ],
        showGroupsOptions: [
            (s) => [s.groupsEnabled, s.groupTypes],
            (enabled, groupTypes) => enabled && groupTypes.length > 0,
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
