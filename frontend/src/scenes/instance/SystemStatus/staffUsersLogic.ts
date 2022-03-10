import { kea } from 'kea'
import api from 'lib/api'
import { UserType } from '~/types'
import { staffUsersLogicType } from './staffUsersLogicType'

export const staffUsersLogic = kea<staffUsersLogicType>({
    path: ['scenes', 'instance', 'SystemStatus', 'staffUsersLogic'],
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
    events: ({ actions }) => ({
        afterMount: [actions.loadStaffUsers],
    }),
})
