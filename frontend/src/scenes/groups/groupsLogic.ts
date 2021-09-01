import { kea } from 'kea'
import api from '../../lib/api'
import { Group, GroupType } from '../../types'
import { teamLogic } from '../teamLogic'
import { groupsLogicType } from './groupsLogicType'

export const groupsLogic = kea<groupsLogicType>({
    reducers: {
        currentGroupType: [
            null as string | null,
            {
                loadGroups: (_, groupType) => groupType,
            },
        ],
    },
    loaders: {
        groupTypes: [
            [] as GroupType[],
            {
                async loadGroupTypes() {
                    if (!teamLogic.values.currentTeam) {
                        return []
                    }
                    const response = await api.get(`api/projects/${teamLogic.values.currentTeam.id}/group_types`)
                    return response['results']
                },
            },
        ],
        groups: [
            [] as Group[],
            {
                async loadGroups(typeKey: string) {
                    if (!teamLogic.values.currentTeam) {
                        return []
                    }
                    const response = await api.get(
                        `api/projects/${teamLogic.values.currentTeam.id}/group_types/${typeKey}/groups`
                    )
                    return response['results']
                },
            },
        ],
    },
    urlToAction: ({ actions }) => ({
        '/groups': () => {
            actions.loadGroupTypes()
        },
        '/groups/:id': ({ id }) => {
            actions.loadGroups(id)
        },
    }),
})
