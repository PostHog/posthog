import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'
import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlResponseType,
    AccessControlType,
    AccessControlTypeRole,
    AccessControlUpdateType,
    APIScopeObject,
    AvailableFeature,
    RoleType,
} from '~/types'

import type { roleBasedAccessControlLogicType } from './roleBasedAccessControlLogicType'

export type RoleWithResourceAccessControls = {
    role?: RoleType
    accessControlByResource: Record<APIScopeObject, AccessControlTypeRole>
}

export const roleBasedAccessControlLogic = kea<roleBasedAccessControlLogicType>([
    path(['scenes', 'accessControl', 'roleBasedAccessControlLogic']),
    connect(() => ({
        values: [membersLogic, ['sortedMembers'], teamLogic, ['currentTeam'], userLogic, ['hasAvailableFeature']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    })),
    actions({
        updateRoleBasedAccessControls: (
            accessControls: Pick<AccessControlUpdateType, 'resource' | 'access_level' | 'role'>[]
        ) => ({ accessControls }),
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
        roleBasedAccessControls: [
            null as AccessControlResponseType | null,
            {
                loadRoleBasedAccessControls: async () => {
                    const response = await api.get<AccessControlResponseType>(
                        'api/projects/@current/global_access_controls'
                    )
                    return response
                },

                updateRoleBasedAccessControls: async ({ accessControls }) => {
                    for (const control of accessControls) {
                        await api.put<AccessControlTypeRole>('api/projects/@current/global_access_controls', {
                            ...control,
                        })
                    }

                    return values.roleBasedAccessControls
                },
            },
        ],

        roles: [
            null as RoleType[] | null,
            {
                loadRoles: async () => {
                    const response = await api.roles.list()
                    return response?.results || []
                },
                addMembersToRole: async ({ role, members }) => {
                    if (!values.roles) {
                        return null
                    }
                    const newMembers = await Promise.all(
                        members.map(async (userUuid: string) => await api.roles.members.create(role.id, userUuid))
                    )

                    role.members = [...role.members, ...newMembers]

                    return [...values.roles]
                },
                removeMemberFromRole: async ({ role, roleMemberId }) => {
                    if (!values.roles) {
                        return null
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
                if (values.editingRoleId === 'new') {
                    role = await api.roles.create(name)
                } else {
                    role = await api.roles.update(values.editingRoleId, { name })
                }

                actions.loadRoles()
                actions.setEditingRoleId(null)
                actions.selectRoleId(role.id)
            },
        },
    })),

    listeners(({ actions, values }) => ({
        updateRoleBasedAccessControlsSuccess: () => actions.loadRoleBasedAccessControls(),
        loadRolesSuccess: () => {
            if (router.values.hashParams.role) {
                actions.selectRoleId(router.values.hashParams.role)
            }
        },
        deleteRoleSuccess: () => {
            actions.loadRoles()
            actions.setEditingRoleId(null)
            actions.selectRoleId(null)
        },

        setEditingRoleId: () => {
            const existingRole = values.roles?.find((role) => role.id === values.editingRoleId)
            actions.resetEditingRole({
                name: existingRole?.name || '',
            })
        },
    })),

    selectors({
        availableLevels: [
            (s) => [s.roleBasedAccessControls],
            (roleBasedAccessControls): string[] => {
                return roleBasedAccessControls?.available_access_levels ?? []
            },
        ],

        defaultAccessLevel: [
            (s) => [s.roleBasedAccessControls],
            (roleBasedAccessControls): string | null => {
                return roleBasedAccessControls?.default_access_level ?? null
            },
        ],

        defaultResourceAccessControls: [
            (s) => [s.roleBasedAccessControls],
            (roleBasedAccessControls): RoleWithResourceAccessControls => {
                const accessControls = roleBasedAccessControls?.access_controls ?? []

                // Find all acs without a roles (they are the default ones)
                const accessControlByResource = accessControls
                    .filter((control) => !control.role)
                    .reduce(
                        (acc, control) => ({
                            ...acc,
                            [control.resource]: control,
                        }),
                        {} as Record<APIScopeObject, AccessControlTypeRole>
                    )

                return { accessControlByResource }
            },
        ],

        rolesWithResourceAccessControls: [
            (s) => [s.roles, s.roleBasedAccessControls, s.defaultResourceAccessControls],
            (roles, roleBasedAccessControls, defaultResourceAccessControls): RoleWithResourceAccessControls[] => {
                if (!roles) {
                    return []
                }

                const accessControls = roleBasedAccessControls?.access_controls ?? []

                return [
                    defaultResourceAccessControls,
                    ...roles.map((role) => {
                        const accessControlByResource = accessControls
                            .filter((control) => control.role === role.id)
                            .reduce(
                                (acc, control) => ({
                                    ...acc,
                                    [control.resource]: control,
                                }),
                                {} as Record<APIScopeObject, AccessControlTypeRole>
                            )

                        return { role, accessControlByResource }
                    }),
                ]
            },
        ],

        resources: [
            () => [],
            (): AccessControlType['resource'][] => {
                // TODO: Sync this as an enum
                return ['feature_flag', 'dashboard', 'insight', 'notebook']
            },
        ],

        canEditRoleBasedAccessControls: [
            (s) => [s.roleBasedAccessControls],
            (roleBasedAccessControls): boolean | null => {
                return roleBasedAccessControls?.user_can_edit_access_levels ?? null
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS)) {
            actions.loadRoles()
            actions.loadRoleBasedAccessControls()
            actions.ensureAllMembersLoaded()
        }
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
