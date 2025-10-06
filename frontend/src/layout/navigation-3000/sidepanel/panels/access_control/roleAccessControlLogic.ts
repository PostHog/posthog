import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    APIScopeObject,
    AccessControlResponseType,
    AccessControlTypeRole,
    OrganizationMemberType,
    RoleType,
} from '~/types'

import type { roleAccessControlLogicType } from './roleAccessControlLogicType'

export type DefaultResourceAccessControls = {
    accessControlByResource: Record<APIScopeObject, AccessControlTypeRole>
}
export type MemberResourceAccessControls = DefaultResourceAccessControls & {
    organization_member?: OrganizationMemberType
}
export type RoleResourceAccessControls = DefaultResourceAccessControls & {
    role?: RoleType
}

export const roleAccessControlLogic = kea<roleAccessControlLogicType>([
    path(['scenes', 'accessControl', 'roleAccessControlLogic']),
    connect(() => ({
        values: [membersLogic, ['sortedMembers'], teamLogic, ['currentTeam'], userLogic, ['hasAvailableFeature']],
        actions: [membersLogic, ['ensureAllMembersLoaded'], organizationLogic, ['loadCurrentOrganization']],
    })),
    actions({
        selectRoleId: (roleId: RoleType['id'] | null) => ({ roleId }),
        deleteRole: (roleId: RoleType['id']) => ({ roleId }),
        removeMemberFromRole: (role: RoleType, roleMemberId: string) => ({ role, roleMemberId }),
        addMembersToRole: (role: RoleType, members: string[]) => ({ role, members }),
        setEditingRoleId: (roleId: string | null) => ({ roleId }),
    }),
    reducers({
        selectedRoleId: [
            null as string | null,
            {
                selectRoleId: (_, { roleId }) => roleId,
            },
        ],
        editingRoleId: [
            null as string | null,
            {
                setEditingRoleId: (_, { roleId }) => roleId,
            },
        ],
    }),
    loaders(({ values }) => ({
        roles: [
            [] as RoleType[],
            {
                loadRoles: async () => {
                    const response = await api.roles.list()
                    return response?.results || []
                },
                addMembersToRole: async ({ role, members }) => {
                    if (!values.roles) {
                        return []
                    }
                    const newMembers = await Promise.all(
                        members.map(async (userUuid: string) => await api.roles.members.create(role.id, userUuid))
                    )

                    role.members = [...role.members, ...newMembers]

                    return [...values.roles]
                },
                removeMemberFromRole: async ({ role, roleMemberId }) => {
                    if (!values.roles) {
                        return []
                    }
                    await api.roles.members.delete(role.id, roleMemberId)
                    role.members = role.members.filter((roleMember) => roleMember.id !== roleMemberId)
                    return [...values.roles]
                },
                deleteRole: async ({ roleId }) => {
                    const role = values.roles?.find((r) => r.id === roleId)
                    if (!role) {
                        return values.roles
                    }
                    await api.roles.delete(role.id)
                    lemonToast.success(`Role "${role.name}" deleted`)
                    return values.roles?.filter((r) => r.id !== role.id) || []
                },
            },
        ],

        resourceAccessControls: [
            null as AccessControlResponseType | null,
            {
                loadResourceAccessControls: async () => {
                    const response = await api.get<AccessControlResponseType>(
                        'api/projects/@current/resource_access_controls'
                    )
                    return response
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        editingRole: {
            defaults: {
                name: '',
            },
            errors: ({ name }) => {
                return {
                    name: !name ? 'Please choose a name for the role' : null,
                }
            },
            submit: async ({ name }) => {
                if (!values.editingRoleId) {
                    return
                }
                let role: RoleType | null = null
                try {
                    if (values.editingRoleId === 'new') {
                        role = await api.roles.create(name)
                    } else {
                        role = await api.roles.update(values.editingRoleId, { name })
                    }

                    actions.loadRoles()
                    actions.setEditingRoleId(null)
                    actions.selectRoleId(role.id)
                } catch (e) {
                    const error = (e as Record<string, any>).detail || 'Failed to save role'
                    lemonToast.error(error)
                }
            },
        },
    })),

    selectors({
        sortedRoles: [
            (s) => [s.roles],
            (roles: RoleType[]): RoleType[] => {
                return [...roles].sort((a, b) => a.name.localeCompare(b.name))
            },
        ],
        canEditRoles: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls: AccessControlResponseType | null): boolean | null => {
                return resourceAccessControls?.user_can_edit_access_levels ?? null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadRolesSuccess: () => {
            if (router.values.hashParams.role) {
                actions.selectRoleId(router.values.hashParams.role)
            }
        },
        deleteRoleSuccess: () => {
            actions.loadRoles()
            actions.setEditingRoleId(null)
            actions.selectRoleId(null)
            actions.loadCurrentOrganization()
        },

        setEditingRoleId: () => {
            const existingRole = values.roles?.find((role) => role.id === values.editingRoleId)
            actions.resetEditingRole({
                name: existingRole?.name || '',
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRoles()
        actions.ensureAllMembersLoaded()
        actions.loadResourceAccessControls()
    }),

    actionToUrl(({ values }) => ({
        selectRoleId: () => {
            const { currentLocation } = router.values
            return [
                currentLocation.pathname,
                currentLocation.searchParams,
                {
                    ...currentLocation.hashParams,
                    role: values.selectedRoleId ?? undefined,
                },
            ]
        },
    })),
])
