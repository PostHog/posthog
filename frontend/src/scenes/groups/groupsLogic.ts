import { kea } from 'kea'
import api from '../../lib/api'
import { Group, GroupType } from '../../types'
import { groupsLogicType } from './groupsLogicType'

interface RelatedGroup {
    key: string
    type_id: string
    type_key: string
}

export const groupsLogic = kea<groupsLogicType<RelatedGroup>>({
    actions: {
        setCurrentGroupId: (id: string) => ({ id }),
        setCurrentGroupType: (groupTypeName: string) => ({ groupTypeName }),
    },
    reducers: {
        currentGroupType: [
            null as string | null,
            {
                loadGroups: (_, groupType) => groupType,
                setCurrentGroupType: (_, { groupTypeName }) => groupTypeName,
            },
        ],
        currentGroupId: [
            null as string | null,
            {
                setCurrentGroupId: (_, { id }) => id,
            },
        ],
    },
    loaders: ({ values, actions }) => ({
        groupTypes: [
            [] as GroupType[],
            {
                loadGroupTypes: async () => {
                    const response = await api.get(`api/projects/@current/group_types`)
                    if (response.length > 0 && !values.currentGroupType) {
                        actions.setCurrentGroupType(response[0].type_key)
                    }

                    return response
                },
            },
        ],
        groups: [
            [] as Group[],
            {
                loadGroups: async (typeKey: string) => {
                    const response = await api.get(`api/projects/@current/group_types/${typeKey}/groups`)

                    // only needed because of demo data gen, should never happen
                    const uniqueGroups: Record<string, Group> = {}

                    for (const group of response) {
                        uniqueGroups[group.id] = group
                    }

                    return Object.values(uniqueGroups)
                },
            },
        ],
        relatedGroups: [
            null as RelatedGroup[] | null,
            {
                loadRelatedGroups: async ({ typeId, id } = {}) => {
                    typeId = typeId || values.currentGroup.type_id
                    id = id || values.currentGroup.id
                    return await api.get(`api/projects/@current/group_types/related?type_id=${typeId}&id=${id}`)
                },
                setCurrentGroupId: () => null,
                setCurrentGroupType: () => null,
            },
        ],
    }),

    selectors: {
        currentGroup: [
            (s) => [s.currentGroupId, s.groups],
            (currentGroupId, groups) => groups.filter((g) => g.id === currentGroupId)[0] ?? null,
        ],
        groupTypeIdToKey: [
            (s) => [s.groupTypes],
            (groupTypes) => {
                const groupTypeIdToKeyMap: Record<number, string> = {}
                for (const groupType of groupTypes) {
                    groupTypeIdToKeyMap[groupType.type_id] = groupType.type_key
                }

                return groupTypeIdToKeyMap
            },
        ],
    },

    listeners: ({ actions }) => ({
        setCurrentGroupType: ({ groupTypeName }) => {
            actions.loadGroups(groupTypeName)
        },
    }),

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
