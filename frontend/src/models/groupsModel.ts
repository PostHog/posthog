import { kea } from 'kea'
import api from 'lib/api'
import { GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsModelType } from './groupsModelType'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export const groupsModel = kea<groupsModelType>({
    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['clickhouseEnabled'],
        ],
    },
    loaders: ({ values }) => ({
        groupTypes: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    if (values.groupsEnabled) {
                        return await api.get(`api/projects/${values.currentTeamId}/groups`)
                    }
                    return []
                },
            },
        ],
    }),
    selectors: {
        groupsEnabled: [
            (s) => [s.featureFlags, s.clickhouseEnabled],
            (featureFlags, clickhouseEnabled) => featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS] && clickhouseEnabled,
        ],
        taxonomicTypesWithGroups: [
            (s) => [s.groupsEnabled, s.groupTypes],
            (groupsEnabled, groupTypes) => {
                if (groupsEnabled) {
                    return [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupTypes.map(
                            (groupType: GroupType) => `${TaxonomicFilterGroupType.Groups}_${groupType.group_type_index}`
                        ),
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                    ] as TaxonomicFilterGroupType[]
                }
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupTypes,
    }),
})
