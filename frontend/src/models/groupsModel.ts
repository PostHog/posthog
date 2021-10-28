import { kea } from 'kea'
import api from 'lib/api'
import { GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsModelType } from './groupsModelType'

export const groupsModel = kea<groupsModelType>({
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    loaders: ({ values }) => ({
        groupTypes: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    if (featureFlagLogic.values.featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS]) {
                        return await api.get(`api/projects/${values.currentTeamId}/groups`)
                    }
                    return []
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupTypes,
    }),
})
