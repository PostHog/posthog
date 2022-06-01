import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb, Group } from '~/types'
import type { groupLogicType } from './groupLogicType'
import { urls } from 'scenes/urls'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'

export const groupLogic = kea<groupLogicType>({
    path: ['groups', 'groupLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], groupsModel, ['groupTypes', 'aggregationLabel']] },
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
            (s) => [s.aggregationLabel, s.groupTypeIndex],
            (aggregationLabel, index): string => aggregationLabel(index).singular,
        ],
        breadcrumbs: [
            (s) => [s.groupTypeName, s.groupTypeIndex, s.groupKey, s.groupData],
            (groupTypeName, groupTypeIndex, groupKey, groupData): Breadcrumb[] => [
                {
                    name: capitalizeFirstLetter(groupTypeName),
                    path: urls.groups(String(groupTypeIndex)),
                },
                {
                    name: groupDisplayId(groupKey, groupData?.group_properties || {}),
                    path: urls.group(String(groupTypeIndex), groupKey),
                },
            ],
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
