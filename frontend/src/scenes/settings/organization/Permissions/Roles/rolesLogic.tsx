import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamMembersLogic } from 'scenes/settings/project/teamMembersLogic'

import { AccessLevel, Resource, RoleMemberType, RoleType, UserBasicType } from '~/types'

import type { rolesLogicType } from './rolesLogicType'

export const rolesLogic = kea<rolesLogicType>([
    path(['scenes', 'organization', 'rolesLogic']),
    connect({ values: [teamMembersLogic, ['allMembers']] }),
    actions({
        setCreateRoleModalShown: (shown: boolean) => ({ shown }),
        setRoleInFocus: (role: null | RoleType) => ({ role }),
        setRoleMembersInFocus: (roleMembers: RoleMemberType[]) => ({ roleMembers }),
        setRoleMembersToAdd: (uuids: string[]) => ({ uuids }),
        openCreateRoleModal: true,
        setPermission: (resource: Resource, access: AccessLevel) => ({ resource, access }),
        clearPermission: true,
        updateRole: (role: RoleType) => ({ role }),
    }),
    reducers({
        createRoleModalShown: [
            false,
            {
                setCreateRoleModalShown: (_, { shown }) => shown,
            },
        ],
        roleInFocus: [
            null as null | RoleType,
            {
                setRoleInFocus: (_, { role }) => role,
            },
        ],
        roleMembersInFocus: [
            [] as RoleMemberType[],
            {
                setRoleMembersInFocus: (_, { roleMembers }) => roleMembers,
            },
        ],
        roleMembersToAdd: [
            [] as string[],
            {
                setRoleMembersToAdd: (_, { uuids }) => uuids,
            },
        ],
        roles: [
            [] as RoleType[],
            {
                updateRole: (state, { role: newRole }) => {
                    return state.map((role) => (role.id == newRole.id ? newRole : role))
                },
            },
        ],
    }),
    loaders(({ values, actions, asyncActions }) => ({
        roles: {
            loadRoles: async () => {
                const response = await api.roles.list()
                return response?.results || []
            },
            createRole: async (roleName: string) => {
                const { roles, roleMembersToAdd } = values
                const newRole = await api.roles.create(roleName)
                await asyncActions.addRoleMembers({ role: newRole, membersToAdd: roleMembersToAdd })
                eventUsageLogic.actions.reportRoleCreated(roleName)
                actions.setRoleMembersInFocus([])
                actions.setRoleMembersToAdd([])
                actions.clearPermission()
                actions.setCreateRoleModalShown(false)
                return [newRole, ...roles]
            },
            deleteRole: async (role: RoleType) => {
                await api.roles.delete(role.id)
                return values.roles.filter((currRoles) => currRoles.id !== role.id)
            },
        },
        roleMembersInFocus: [
            [] as RoleMemberType[],
            {
                loadRoleMembers: async ({ roleId }) => {
                    const response = await api.roles.members.list(roleId)
                    return response?.results || []
                },
                addRoleMembers: async ({ role, membersToAdd }) => {
                    const newMembers = await Promise.all(
                        membersToAdd.map(async (userUuid: string) => await api.roles.members.create(role.id, userUuid))
                    )
                    actions.setRoleMembersToAdd([])
                    return [...values.roleMembersInFocus, ...newMembers]
                },
                deleteRoleMember: async ({ roleMemberUuid }) => {
                    values.roleInFocus && (await api.roles.members.delete(values.roleInFocus.id, roleMemberUuid))
                    return values.roleMembersInFocus.filter((member) => member.id !== roleMemberUuid)
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setRoleInFocus: ({ role }) => {
            role && actions.loadRoleMembers({ roleId: role.id })
            actions.setCreateRoleModalShown(true)
        },
        openCreateRoleModal: () => {
            actions.setRoleInFocus(null)
            actions.setRoleMembersInFocus([])
            actions.setCreateRoleModalShown(true)
        },
        setCreateRoleModalShown: () => {
            if (values.roleInFocus) {
                actions.setPermission(Resource.FEATURE_FLAGS, values.roleInFocus.feature_flags_access_level)
            } else {
                actions.setPermission(Resource.FEATURE_FLAGS, AccessLevel.WRITE)
            }
        },
        deleteRoleSuccess: () => {
            actions.setCreateRoleModalShown(false)
        },
    })),
    selectors({
        addableMembers: [
            (s) => [s.allMembers, s.roleMembersInFocus],
            (allMembers, roleMembersInFocus): UserBasicType[] => {
                const addableMembers: UserBasicType[] = []
                for (const member of allMembers) {
                    if (
                        !roleMembersInFocus.some(
                            (roleMember: RoleMemberType) => roleMember.user.uuid === member.user.uuid
                        )
                    ) {
                        addableMembers.push(member.user)
                    }
                }
                addableMembers.sort((a, b) => a.first_name.localeCompare(b.first_name))
                return addableMembers
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRoles()
    }),
])
