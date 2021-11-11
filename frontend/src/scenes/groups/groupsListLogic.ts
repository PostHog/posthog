import { kea } from 'kea'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'

export const groupsListLogic = kea<groupsListLogic>({
    path: ['groups', 'groupsListLogic'],
    connect: { values: [groupsModel, ['groupsEnabled']] },
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
                        return await api.get(
                            `api/projects/${values.currentTeamId}/groups/?group_type_index=${groupTypeIndex}`
                        )
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
        '/persons/groups/:id': ({ id }) => {
            actions.loadGroupList(id)
            actions.setTab(id)
        },
    }),
})
