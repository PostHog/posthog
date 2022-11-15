import { actions, kea, reducers, path, connect, selectors, afterMount, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamMembersLogic } from 'scenes/project/Settings/teamMembersLogic'
import { RoleMemberType, RoleType, UserBasicType } from '~/types'
import { rolesLogicType } from './rolesLogicType'

export const rolesLogic = kea<rolesLogicType>([
    path(['scenes', 'organization', 'rolesLogic']),
    connect({ values: [teamMembersLogic, ['plainMembers']] }),
    actions({
        setCreateRoleModalShown: (shown: boolean) => ({ shown }),
        setRoleInFocus: (role: null | RoleType) => ({ role }),
        setRoleMembersInFocus: (roleMembers: RoleMemberType[]) => ({ roleMembers }),
        setRoleMembersToAdd: (uuids: string[]) => ({ uuids }),
        openCreateRoleModal: true,
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
    }),
    loaders(({ values, actions }) => ({
        roles: [
            [] as RoleType[],
            {
                loadRoles: async () => {
                    const response = await api.roles.list()
                    return response?.results || []
                },
                createRole: async (roleName: string) => {
                    const { roles, roleMembersToAdd } = values
                    const newRole = await api.roles.create(roleName)
                    await actions.addRoleMembers({ role: newRole, membersToAdd: roleMembersToAdd })
                    actions.setRoleMembersInFocus([])
                    actions.setRoleMembersToAdd([])
                    actions.setCreateRoleModalShown(false)
                    return [newRole, ...roles]
                },
                deleteRole: async (role: RoleType) => {
                    await api.roles.delete(role.id)
                    return values.roles.filter((currRoles) => currRoles.id !== role.id)
                },
            },
        ],
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
    listeners(({ actions }) => ({
        setRoleInFocus: ({ role }) => {
            role && actions.loadRoleMembers({ roleId: role.id })
            actions.setCreateRoleModalShown(true)
        },
        openCreateRoleModal: () => {
            actions.setRoleInFocus(null)
            actions.setRoleMembersInFocus([])
            actions.setCreateRoleModalShown(true)
        },
    })),
    selectors({
        addableMembers: [
            (s) => [s.plainMembers, s.roleMembersInFocus],
            (plainMembers, roleMembersInFocus): UserBasicType[] => {
                const addableMembers: UserBasicType[] = []
                for (const plainMember of plainMembers) {
                    if (
                        !roleMembersInFocus.some(
                            (roleMember: RoleMemberType) => roleMember.user.uuid === plainMember.user.uuid
                        )
                    ) {
                        addableMembers.push(plainMember.user)
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
