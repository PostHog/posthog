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
    AccessControlResourceType,
    AccessControlResponseType,
    AccessControlType,
    AccessControlTypeRole,
    AccessControlUpdateType,
    APIScopeObject,
    AvailableFeature,
    OrganizationMemberType,
    RoleType,
} from '~/types'

import type { roleBasedAccessControlLogicType } from './roleBasedAccessControlLogicType'

export type DefaultResourceAccessControls = {
    accessControlByResource: Record<APIScopeObject, AccessControlTypeRole>
}
export type MemberResourceAccessControls = DefaultResourceAccessControls & {
    organization_member?: OrganizationMemberType
}
export type RoleResourceAccessControls = DefaultResourceAccessControls & {
    role?: RoleType
}

export const roleBasedAccessControlLogic = kea<roleBasedAccessControlLogicType>([
    path(['scenes', 'accessControl', 'roleBasedAccessControlLogic']),
    connect({
        values: [
            membersLogic,
            ['sortedMembers'],
            teamLogic,
            ['currentTeam'],
            userLogic,
            ['hasAvailableFeature'],
            membersLogic,
            ['sortedMembers'],
        ],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        updateResourceAccessControls: (
            accessControls: Pick<
                AccessControlUpdateType,
                'resource' | 'access_level' | 'role' | 'organization_member'
            >[]
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
        resourceAccessControls: [
            null as AccessControlResponseType | null,
            {
                loadResourceAccessControls: async () => {
                    const response = await api.get<AccessControlResponseType>(
                        'api/projects/@current/global_access_controls'
                    )
                    return response
                },

                updateResourceAccessControls: async ({ accessControls }) => {
                    for (const control of accessControls) {
                        await api.put<AccessControlTypeRole>('api/projects/@current/global_access_controls', {
                            ...control,
                        })
                    }

                    return values.resourceAccessControls
                },
            },
        ],

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

    listeners(({ actions, values }) => ({
        updateResourceAccessControlsSuccess: () => actions.loadResourceAccessControls(),
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
            (s) => [s.resourceAccessControls],
            (resourceAccessControls): string[] => {
                return resourceAccessControls?.available_access_levels ?? []
            },
        ],

        defaultAccessLevel: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls): string | null => {
                return resourceAccessControls?.default_access_level ?? null
            },
        ],

        defaultResourceAccessControls: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls): DefaultResourceAccessControls => {
                const accessControls = resourceAccessControls?.access_controls ?? []

                // Find all acs without a roles (they are the default ones)
                const accessControlByResource = accessControls
                    .filter((control) => !control.role && !control.organization_member)
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

        memberResourceAccessControls: [
            (s) => [s.sortedMembers, s.resourceAccessControls],
            (
                sortedMembers: OrganizationMemberType[] | null,
                resourceAccessControls: AccessControlResponseType | null
            ): MemberResourceAccessControls[] => {
                if (!sortedMembers) {
                    return []
                }

                const accessControls = resourceAccessControls?.access_controls ?? []

                return (sortedMembers || [])
                    .map((member: OrganizationMemberType) => {
                        const accessControlByResource = accessControls
                            .filter((control: AccessControlType) => control.organization_member === member.id)
                            .reduce(
                                (acc: Record<APIScopeObject, AccessControlTypeRole>, control: AccessControlType) => ({
                                    ...acc,
                                    [control.resource]: control as AccessControlTypeRole,
                                }),
                                {} as Record<APIScopeObject, AccessControlTypeRole>
                            )

                        // Only include members that have at least one access control
                        // if (Object.keys(accessControlByResource).length === 0) {
                        //     return null
                        // }

                        return { organization_member: member, accessControlByResource }
                    })
                    .filter(Boolean) as MemberResourceAccessControls[]
            },
        ],

        roleResourceAccessControls: [
            (s) => [s.roles, s.resourceAccessControls],
            (
                roles: RoleType[] | null,
                resourceAccessControls: AccessControlResponseType | null
            ): RoleResourceAccessControls[] => {
                if (!roles) {
                    return []
                }

                const accessControls = resourceAccessControls?.access_controls ?? []

                return (roles || [])
                    .map((role: RoleType) => {
                        const accessControlByResource = accessControls
                            .filter((control: AccessControlType) => control.role === role.id)
                            .reduce(
                                (acc: Record<APIScopeObject, AccessControlTypeRole>, control: AccessControlType) => ({
                                    ...acc,
                                    [control.resource]: control as AccessControlTypeRole,
                                }),
                                {} as Record<APIScopeObject, AccessControlTypeRole>
                            )

                        // Only include roles that have at least one access control
                        // if (Object.keys(accessControlByResource).length === 0) {
                        //     return null
                        // }

                        return { role, accessControlByResource }
                    })
                    .filter(Boolean) as RoleResourceAccessControls[]
            },
        ],

        resources: [
            () => [],
            (): AccessControlType['resource'][] => {
                return [
                    AccessControlResourceType.FeatureFlag,
                    AccessControlResourceType.Dashboard,
                    AccessControlResourceType.Insight,
                    AccessControlResourceType.Notebook,
                ]
            },
        ],

        canEditRoleBasedAccessControls: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls): boolean | null => {
                return resourceAccessControls?.user_can_edit_access_levels ?? null
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS)) {
            actions.loadRoles()
            actions.loadResourceAccessControls()
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
