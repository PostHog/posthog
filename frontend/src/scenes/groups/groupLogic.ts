import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { Group, RelatedActor } from '~/types'
import { groupLogicType } from './groupLogicType'

export const groupLogic = kea<groupLogicType>({
    path: ['groups', 'groupLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], groupsModel, ['groupsEnabled', 'groupTypes']] },
    actions: () => ({
        setGroup: (groupTypeIndex: number, groupKey: string) => ({ groupTypeIndex, groupKey }),
    }),
    loaders: ({ values }) => ({
        groupData: [
            null as Group | null,
            {
                loadGroup: async () => {
                    const params = { group_type_index: values.groupTypeIndex, group_key: values.groupKey }
                    const url = `api/projects/${values.currentTeamId}/groups/find?${toParams(params)}`
                    return await api.get(url)
                },
            },
        ],
        relatedActors: [
            [] as RelatedActor[],
            {
                loadRelatedActors: async () => {
                    const params = { group_type_index: values.groupTypeIndex, id: values.groupKey }
                    const url = `api/projects/${values.currentTeamId}/groups/related?${toParams(params)}`

                    return await api.get(url)
                },
                setGroup: () => [],
            },
        ],
    }),
    reducers: {
        groupTypeIndex: [
            0,
            {
                setGroup: (_, { groupTypeIndex }) => groupTypeIndex,
            },
        ],
        groupKey: [
            '',
            {
                setGroup: (_, { groupKey }) => groupKey,
            },
        ],
    },
    selectors: {
        groupTypeName: [
            (s) => [s.groupTypes, s.groupTypeIndex],
            (groupTypes, index): string => groupTypes[index]?.group_type || '',
        ],
    },
    urlToAction: ({ actions }) => ({
        '/groups/:groupTypeIndex/:groupKey': ({ groupTypeIndex, groupKey }) => {
            if (groupTypeIndex && groupKey) {
                actions.setGroup(+groupTypeIndex, decodeURIComponent(groupKey))
                actions.loadGroup()
            }
        },
    }),
})
