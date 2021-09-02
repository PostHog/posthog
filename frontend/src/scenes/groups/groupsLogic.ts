import { kea } from 'kea'
import api from '../../lib/api'
import { Group, GroupType } from '../../types'
import { teamLogic } from '../teamLogic'
import { groupsLogicType } from './groupsLogicType'

export const groupsLogic = kea<groupsLogicType>({
    actions: {
        setCurrentGroupId: (id: string) => ({ id }),
    },
    reducers: {
        currentGroupType: [
            null as string | null,
            {
                loadGroups: (_, groupType) => groupType,
            },
        ],
        currentGroupId: [
            null as string | null,
            {
                setCurrentGroupId: (_, { id }) => id,
            },
        ],
    },
    loaders: {
        groupTypes: [
            [] as GroupType[],
            {
                loadGroupTypes: async () => {
                    if (!teamLogic.values.currentTeam) {
                        return []
                    }
                    const response = await api.get(`api/projects/${teamLogic.values.currentTeam.id}/group_types`)
                    return response
                },
            },
        ],
        groups: [
            [] as Group[],
            {
                loadGroups: async (typeKey: string) => {
                    if (!teamLogic.values.currentTeam) {
                        return []
                    }
                    const response = await api.get(
                        `api/projects/${teamLogic.values.currentTeam.id}/group_types/${typeKey}/groups`
                    )
                    return response
                },
            },
        ],
    },

    selectors: {
        currentGroup: [
            (s) => [s.currentGroupId, s.groups],
            (currentGroupId, groups) => groups.filter((g) => g.id === currentGroupId)[0] ?? null,
        ],
    },

    urlToAction: ({ actions }) => ({
        '/groups': () => {
            actions.loadGroupTypes()
        },
        '/groups/:type': ({ type }) => {
            if (type) {
                actions.loadGroups(type)
            }
        },
        '/groups/:type/:id': ({ type, id }) => {
            if (type) {
                actions.loadGroups(type)
            }
            if (id) {
                actions.setCurrentGroupId(id)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadGroupTypes()
        },
    }),
})
