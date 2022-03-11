import { kea } from 'kea'
import api from 'lib/api'
import { UserType } from '~/types'
import { staffUsersLogicType } from './staffUsersLogicType'

export const staffUsersLogic = kea<staffUsersLogicType>({
    path: ['scenes', 'instance', 'SystemStatus', 'staffUsersLogic'],
    actions: {
        setStaffUsersToBeAdded: (userUuids: string[]) => ({ userUuids }),
        addStaffUsers: true,
        deleteStaffUser: (userUuid: string) => ({ userUuid }),
    },
    reducers: {
        staffUsersToBeAdded: [
            [] as string[],
            {
                setStaffUsersToBeAdded: (_, { userUuids }) => userUuids,
            },
        ],
    },
    loaders: ({ actions, values }) => ({
        allUsers: [
            [] as UserType[],
            {
                loadAllUsers: async () => {
                    return (await api.get('api/users')).results ?? []
                },
                addStaffUsers: async () => {
                    const { staffUsersToBeAdded, allUsers } = values
                    actions.setStaffUsersToBeAdded([])
                    const newStaffUsers = await Promise.all(
                        staffUsersToBeAdded.map(
                            async (userUuid) =>
                                (await api.update(`api/users/${userUuid}`, { is_staff: true })) as UserType
                        )
                    )
                    const updatedAllUsers: UserType[] = [
                        ...allUsers.filter(({ uuid }) => !staffUsersToBeAdded.includes(uuid)),
                        ...newStaffUsers,
                    ]
                    updatedAllUsers.sort((a, b) => a.first_name.localeCompare(b.first_name))
                    return updatedAllUsers
                },
                deleteStaffUser: async ({ userUuid }) => {
                    await api.update(`api/users/${userUuid}`, { is_staff: false })
                    const updatedAllUsers = [...values.allUsers]
                    for (const user of updatedAllUsers) {
                        if (user.uuid === userUuid) {
                            user.is_staff = false
                        }
                    }
                    return updatedAllUsers
                },
            },
        ],
    }),
    selectors: {
        staffUsers: [(s) => [s.allUsers], (allUsers): UserType[] => allUsers.filter((user) => user.is_staff)],
        nonStaffUsers: [(s) => [s.allUsers], (allUsers): UserType[] => allUsers.filter((user) => !user.is_staff)],
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadAllUsers],
    }),
})
