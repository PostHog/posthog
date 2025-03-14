import { LemonDialog, LemonInput } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { UserBasicType, UserGroup } from '~/types'

import type { userGroupsLogicType } from './userGroupsLogicType'

export interface UserGroupsFuse extends Fuse<UserGroup> {}

export const userGroupsLogic = kea<userGroupsLogicType>([
    path(['scenes', 'settings', 'environment', 'userGroupsLogic']),

    actions({
        ensureAllGroupsLoaded: true,
        openGroupCreationForm: true,
        setSearch: (search) => ({ search }),
    }),

    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),

    loaders(({ values }) => ({
        userGroups: [
            [] as UserGroup[],
            {
                loadUserGroups: async () => {
                    const response = await api.userGroups.list()
                    return response.results
                },
                deleteUserGroup: async (id: string) => {
                    await api.userGroups.delete(id)
                    const newValues = [...values.userGroups]
                    return newValues.filter((v) => v.id !== id)
                },
                createUserGroup: async (name: string) => {
                    const response = await api.userGroups.create(name)
                    return [...values.userGroups, response]
                },
                addMember: async ({ id, user }: { id: string; user: UserBasicType }) => {
                    const group = values.userGroups.find((g) => g.id === id)
                    if (group) {
                        await api.userGroups.addMember(id, user.id)
                        group.members = [...group.members, user]
                        return values.userGroups.map((g) => (g.id === id ? group : g))
                    }
                    return values.userGroups
                },
                removeMember: async ({ id, user }: { id: string; user: UserBasicType }) => {
                    const group = values.userGroups.find((g) => g.id === id)
                    if (group) {
                        await api.userGroups.removeMember(id, user.id)
                        group.members = group.members.filter((m) => m.id !== user.id)
                        return values.userGroups.map((g) => (g.id === id ? group : g))
                    }
                    return values.userGroups
                },
            },
        ],
    })),

    selectors({
        userGroupsFuse: [
            (s) => [s.userGroups],
            (userGroups): UserGroupsFuse => new Fuse<UserGroup>(userGroups, { keys: ['name'], threshold: 0.3 }),
        ],
        filteredGroups: [
            (s) => [s.userGroups, s.userGroupsFuse, s.search],
            (userGroups, userGroupsFuse, search): UserGroup[] =>
                search ? userGroupsFuse.search(search).map((result) => result.item) : userGroups ?? [],
        ],
    }),

    listeners(({ values, actions }) => ({
        openGroupCreationForm: () => {
            LemonDialog.openForm({
                title: 'Create user group',
                initialValues: { name: '' },
                content: (
                    <LemonField name="name">
                        <LemonInput placeholder="Name" autoFocus />
                    </LemonField>
                ),
                errors: { name: (name) => (!name ? 'You must enter a name' : undefined) },
                onSubmit: ({ name }) => actions.createUserGroup(name),
            })
        },

        ensureAllGroupsLoaded: () => {
            if (values.userGroupsLoading) {
                return
            }
            if (values.userGroups.length === 0) {
                actions.loadUserGroups()
            }
        },
    })),
])
