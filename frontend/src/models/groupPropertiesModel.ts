import { kea } from 'kea'
import { groupPropertiesModelType } from './groupPropertiesModelType'
import api from 'lib/api'
import { GroupTypeProperties, PersonProperty } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from './groupsModel'

export const groupPropertiesModel = kea<groupPropertiesModelType>({
    path: ['models', 'groupPropertiesModel'],
    connect: {
        values: [teamLogic, ['currentTeamId'], groupsModel, ['groupsEnabled']],
    },
    loaders: ({ values }) => ({
        allGroupProperties: [
            {} as GroupTypeProperties,
            {
                loadAllGroupProperties: async () => {
                    if (values.groupsEnabled) {
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
                    groupProperties[groupTypeIndex] || [],
        ],
        groupProperties_0: [(s) => [s.allGroupProperties], (groupProperties) => groupProperties['0']],
        groupProperties_1: [(s) => [s.allGroupProperties], (groupProperties) => groupProperties['1']],
        groupProperties_2: [(s) => [s.allGroupProperties], (groupProperties) => groupProperties['2']],
        groupProperties_3: [(s) => [s.allGroupProperties], (groupProperties) => groupProperties['3']],
        groupProperties_4: [(s) => [s.allGroupProperties], (groupProperties) => groupProperties['4']],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupProperties,
    }),
})
