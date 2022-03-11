import { kea } from 'kea'
import api from 'lib/api'
import { UserType } from '~/types'
import { staffUsersLogicType } from './staffUsersLogicType'

export const staffUsersLogic = kea<staffUsersLogicType>({
    path: ['scenes', 'instance', 'SystemStatus', 'staffUsersLogic'],
    actions: {
        setStaffUsersToBeAdded: (userIds: string[]) => ({ userIds }),
        addStaffUsers: true,
    },
    reducers: {
        staffUsersToBeAdded: [
            [] as string[],
            {
                setStaffUsersToBeAdded: (_, { userIds }) => userIds,
            },
        ],
    },
    loaders: {
        staffUsers: [
            [] as UserType[],
            {
                loadStaffUsers: async () => {
                    return (await api.get('api/users?is_staff=true')).results ?? []
                },
            },
        ],
        nonStaffUsers: [
            [] as UserType[],
            {
                loadNonStaffUsers: async () => {
                    return (await api.get('api/users?is_staff=false')).results ?? []
                },
            },
        ],
    },
    listeners: {
        addStaffUsers: async () => {
            console.log(1)
        },
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadStaffUsers],
    }),
})
