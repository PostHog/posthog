import { kea } from 'kea'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb, Group } from '~/types'
import { groupsListLogicType } from './groupsListLogicType'

interface GroupsPaginatedResponse {
    next: string | null
    previous: string | null
    results: Group[]
}

export const groupsListLogic = kea<groupsListLogicType<GroupsPaginatedResponse>>({
    path: ['groups', 'groupsListLogic'],
    connect: { values: [teamLogic, ['currentTeamId'], groupsModel, ['groupsEnabled', 'groupTypes']] },
    actions: () => ({
        loadGroups: (url?: string | null) => ({ url }),
        setTab: (tab: string) => ({ tab }),
    }),
    loaders: ({ values }) => ({
        groups: [
            { next: null, previous: null, results: [] } as GroupsPaginatedResponse,
            {
                loadGroups: async ({ url }) => {
                    if (values.groupsEnabled) {
                        url =
                            url || `api/projects/${values.currentTeamId}/groups/?group_type_index=${values.currentTab}`
                        return await api.get(url)
                    }
                },
            },
        ],
    }),
    reducers: {
        currentTab: [
            '-1',
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    selectors: {
        currentTabName: [
            (s) => [s.currentTab, s.groupTypes],
            (currentTab, groupTypes): string =>
                currentTab === '-1'
                    ? 'Persons'
                    : groupTypes?.length
                    ? capitalizeFirstLetter(groupTypes[parseInt(currentTab)].group_type)
                    : '',
        ],
        breadcrumbs: [
            (s) => [s.currentTabName, s.currentTab],
            (currentTabName, currentTab): Breadcrumb[] => [
                {
                    name: currentTabName,
                    path: urls.groups(currentTab),
                },
            ],
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
            if (id) {
                actions.setTab(id)
                actions.loadGroups()
            }
        },
    }),
})
