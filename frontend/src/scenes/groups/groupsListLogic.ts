import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'

export const groupsListLogic = kea<groupsListLogic>({
    path: ['groups', 'groupsListLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], groupsModel, ['groupsEnabled', 'groupTypes']] },
    actions: () => ({
        loadGroupList: (groupTypeIndex: string) => ({ groupTypeIndex }),
        setTab: (tab: string) => ({ tab }),
    }),
    loaders: ({ values }) => ({
        groupList: [
            [] as Array<Group>,
            {
                loadGroupList: async ({ groupTypeIndex }) => {
                    if (values.groupsEnabled) {
                        const groups = await api.get(
                            `api/projects/${values.currentTeamId}/groups/?group_type_index=${groupTypeIndex}`
                        )
                        return groups.results
                    }
                    return []
                },
            },
        ],
    }),
    reducers: {
        currentGroup: [
            0,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    actionToUrl: () => ({
        setTab: ({ tab }) => {
            if (tab !== '-1') {
                return urls.groups(tab)
            }
            return urls.persons()
        },
    }),
    urlToAction: ({ actions }) => ({
        '/groups/:id': ({ id }) => {
            actions.loadGroupList(id)
            actions.setTab(id)
        },
    }),
})
