import { kea } from 'kea'
import { groupPropertiesModelType } from './groupPropertiesModelType'
import api from 'lib/api'
import { GroupTypeProperties, PersonProperty } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const groupPropertiesModel = kea<groupPropertiesModelType>({
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    loaders: ({ values }) => ({
        allGroupProperties: [
            {} as GroupTypeProperties,
            {
                loadAllGroupProperties: async () => {
                    if (featureFlagLogic.values.featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS]) {
                        return await api.get(`api/projects/${values.currentTeamId}/groups/property_definitions`)
                    }
                    return {}
                },
            },
        ],
    }),
    selectors: {
        groupProperties: [
            (s) => [s.allGroupProperties],
            (groupProperties: GroupTypeProperties) =>
                (groupTypeIndex: number): Array<PersonProperty> =>
                    groupProperties[groupTypeIndex],
        ],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupProperties,
    }),
})
