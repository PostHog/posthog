import { kea } from 'kea'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'

interface GroupsPaginatedResponse {
    next_url: string | null
    previous_url: string | null
    results: Group[]
}

export const groupsListLogic = kea<groupsListLogic>({
    path: ['groups', 'groupsListLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], groupsModel, ['groupsEnabled', 'groupTypes']] },
    actions: () => ({
        loadGroups: (url?: string | null) => ({ url }),
        setTab: (tab: string) => ({ tab }),
    }),
    loaders: ({ values }) => ({
        groups: [
            { next_url: null, previous_url: null, results: [] } as GroupsPaginatedResponse,
            {
                loadGroups: async ({ url }) => {
                    if (values.groupsEnabled) {
                        if (!url) {
                            return await api.get(
                                `api/projects/${values.currentTeamId}/groups/?group_type_index=${values.currentGroup}`
                            )
                        }
                        return await api.get(url)
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
            actions.setTab(id)
            actions.loadGroups()
        },
    }),
})
