import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { UserType } from '~/types'

import type { staffUsersLogicType } from './staffUsersLogicType'

export const staffUsersLogic = kea<staffUsersLogicType>([
    path(['scenes', 'instance', 'SystemStatus', 'staffUsersLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
        actions: [userLogic, ['loadUser']],
    })),
    actions({
        setStaffUsersToBeAdded: (userUuids: string[]) => ({ userUuids }),
        addStaffUsers: true,
        setStaffUserToBeDeleted: (user: UserType | null) => ({ user }),
        deleteStaffUser: (userUuid: string) => ({ userUuid }),
    }),
    loaders(({ actions, values }) => ({
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
                            async (userUuid) => await api.update<UserType>(`api/users/${userUuid}`, { is_staff: true })
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
                    await api.update<UserType>(`api/users/${userUuid}`, { is_staff: false })
                    if (values.user?.uuid === userUuid) {
                        actions.loadUser() // Loads the main user object to properly reflect staff user changes
                        router.actions.push(urls.projectRoot())
                    }
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
    })),
    reducers({
        staffUsersToBeAdded: [
            [] as string[],
            {
                setStaffUsersToBeAdded: (_, { userUuids }) => userUuids,
            },
        ],
        staffUserToBeDeleted: [
            null as UserType | null,
            {
                setStaffUserToBeDeleted: (_, { user }) => user,
            },
        ],
    }),
    selectors({
        staffUsers: [(s) => [s.allUsers], (allUsers): UserType[] => allUsers.filter((user) => user.is_staff)],
        nonStaffUsers: [(s) => [s.allUsers], (allUsers): UserType[] => allUsers.filter((user) => !user.is_staff)],
    }),
    events(({ actions }) => ({
        afterMount: [actions.loadAllUsers],
    })),
])
