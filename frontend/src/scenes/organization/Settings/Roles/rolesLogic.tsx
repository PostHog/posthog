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
        setRoleInFocus: (role: RoleType) => ({ role }),
        setRoleMembersInFocus: (roleMembers: RoleMemberType[]) => ({ roleMembers }),
        setRoleMembersToAdd: (uuids: string[]) => ({ uuids }),
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
                setRoleInFocus: (_, {role}) => role
            }
        ],
        roleMembersInFocus: [
            [] as RoleMemberType[],
            {
                setRoleMembersInFocus: (_, { roleMembers }) => roleMembers
            }
        ],
        roleMembersToAdd: [
            [] as string[],
            {
                setRoleMembersToAdd: (_, { uuids }) => uuids,
            },
        ]
    }),
    loaders(() => ({
        roles: [
            [] as RoleType[],
            {
                loadRoles: async () => await api.roles.list()
            },
        ],
        roleMembersInFocus: [
            [] as RoleMemberType[],
            {
                loadRoleMembers: async ({ roleId }) => await api.roles.members.list(roleId)
            }
        ]
    })),

    selectors({
        addableMembers: [
            (s) => [s.plainMembers, s.roleMembersInFocus],
            (plainMembers, roleMembersInFocus): UserBasicType[] => {
                const addableMembers: UserBasicType[] = []
                for (const plainMember of plainMembers) {
                    if (!roleMembersInFocus.some((roleMember: RoleMemberType) => roleMember.user.uuid === plainMember.user.uuid)) {
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
    })
])
