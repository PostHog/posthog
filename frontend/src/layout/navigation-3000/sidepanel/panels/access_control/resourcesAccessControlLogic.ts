import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlResourceType,
    AccessControlResponseType,
    AccessControlType,
    AccessControlTypeRole,
    AccessControlUpdateType,
    OrganizationMemberType,
    RoleType,
} from '~/types'

import type { resourcesAccessControlLogicType } from './resourcesAccessControlLogicType'
import { roleAccessControlLogic } from './roleAccessControlLogic'

export type DefaultResourceAccessControls = {
    accessControlByResource: Record<APIScopeObject, AccessControlTypeRole>
}
export type MemberResourceAccessControls = DefaultResourceAccessControls & {
    organization_member?: OrganizationMemberType
}
export type RoleResourceAccessControls = DefaultResourceAccessControls & {
    role?: RoleType
}

export const resourcesAccessControlLogic = kea<resourcesAccessControlLogicType>([
    path(['scenes', 'accessControl', 'resourcesAccessControlLogic']),
    connect(() => ({
        values: [roleAccessControlLogic, ['roles'], teamLogic, ['currentTeam'], membersLogic, ['sortedMembers']],
    })),
    actions({
        updateResourceAccessControls: (
            accessControls: Pick<
                AccessControlUpdateType,
                'resource' | 'access_level' | 'role' | 'organization_member'
            >[],
            saveType: 'member' | 'role' | 'default'
        ) => ({ accessControls, saveType }),
        openMemberModal: (editingMember: MemberResourceAccessControls | null = null) => ({ editingMember }),
        closeMemberModal: true,
        openRoleModal: (editingRole: RoleResourceAccessControls | null = null) => ({ editingRole }),
        closeRoleModal: true,
        openDefaultModal: true,
        closeDefaultModal: true,
    }),
    loaders(({ values }) => ({
        resourceAccessControls: [
            null as AccessControlResponseType | null,
            {
                loadResourceAccessControls: async () => {
                    const response = await api.get<AccessControlResponseType>(
                        'api/projects/@current/resource_access_controls'
                    )
                    return response
                },

                updateResourceAccessControls: async ({ accessControls }) => {
                    for (const control of accessControls) {
                        await api.put<AccessControlTypeRole>('api/projects/@current/resource_access_controls', {
                            ...control,
                        })
                    }

                    return values.resourceAccessControls
                },
            },
        ],
    })),
    reducers({
        memberModalOpen: [
            false as boolean,
            {
                openMemberModal: () => true,
                closeMemberModal: () => false,
            },
        ],
        editingMember: [
            null as MemberResourceAccessControls | null,
            {
                openMemberModal: (_, { editingMember }) => editingMember,
                closeMemberModal: () => null,
            },
        ],
        roleModalOpen: [
            false as boolean,
            {
                openRoleModal: () => true,
                closeRoleModal: () => false,
            },
        ],
        editingRole: [
            null as RoleResourceAccessControls | null,
            {
                openRoleModal: (_, { editingRole }) => editingRole,
                closeRoleModal: () => null,
            },
        ],
        defaultModalOpen: [
            false as boolean,
            {
                openDefaultModal: () => true,
                closeDefaultModal: () => false,
            },
        ],
    }),

    listeners(({ actions, cache }) => ({
        updateResourceAccessControls: ({ saveType }) => {
            cache.pendingSaveType = saveType
        },
        updateResourceAccessControlsSuccess: () => {
            actions.loadResourceAccessControls()
            lemonToast.success('Access controls updated successfully')
            if (cache.pendingSaveType === 'member') {
                actions.closeMemberModal()
            } else if (cache.pendingSaveType === 'role') {
                actions.closeRoleModal()
            } else if (cache.pendingSaveType === 'default') {
                actions.closeDefaultModal()
            }
            cache.pendingSaveType = null
        },
    })),

    selectors({
        availableLevels: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls): AccessControlLevel[] => {
                return resourceAccessControls?.available_access_levels ?? []
            },
        ],

        defaultAccessLevel: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls): string | null => {
                return resourceAccessControls?.default_access_level ?? null
            },
        ],

        organizationAdmins: [
            (s) => [s.sortedMembers],
            (members): OrganizationMemberType[] => {
                return members?.filter((member) => member.level >= OrganizationMembershipLevel.Admin) ?? []
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
                        (acc, control) => Object.assign(acc, { [control.resource]: control }),
                        {} as Record<APIScopeObject, AccessControlTypeRole>
                    )

                return { accessControlByResource }
            },
        ],

        addableMembers: [
            (s) => [s.sortedMembers, s.memberResourceAccessControls, s.organizationAdmins],
            (
                sortedMembers: OrganizationMemberType[] | null,
                memberResourceAccessControls: MemberResourceAccessControls[],
                organizationAdmins: OrganizationMemberType[]
            ): OrganizationMemberType[] => {
                return (
                    sortedMembers?.filter(
                        (member) =>
                            !memberResourceAccessControls.some((m) => m.organization_member?.id === member.id) &&
                            !organizationAdmins.find((admin) => admin.id === member.id)
                    ) || []
                )
            },
        ],

        addableRoles: [
            (s) => [s.roles, s.roleResourceAccessControls],
            (roles: RoleType[] | null, roleResourceAccessControls: RoleResourceAccessControls[]): RoleType[] => {
                return roles?.filter((role) => !roleResourceAccessControls.some((r) => r.role?.id === role.id)) || []
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

                return sortedMembers
                    .map((member: OrganizationMemberType) => {
                        const accessControlByResource = accessControls
                            .filter((control: AccessControlType) => control.organization_member === member.id)
                            .reduce(
                                (acc: Record<APIScopeObject, AccessControlTypeRole>, control: AccessControlType) =>
                                    Object.assign(acc, { [control.resource]: control as AccessControlTypeRole }),
                                {} as Record<APIScopeObject, AccessControlTypeRole>
                            )

                        // Only include members that have at least one access control
                        if (Object.keys(accessControlByResource).length === 0) {
                            return null
                        }

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

                return roles
                    .map((role: RoleType) => {
                        const accessControlByResource = accessControls
                            .filter((control: AccessControlType) => control.role === role.id)
                            .reduce(
                                (acc: Record<APIScopeObject, AccessControlTypeRole>, control: AccessControlType) =>
                                    Object.assign(acc, { [control.resource]: control as AccessControlTypeRole }),
                                {} as Record<APIScopeObject, AccessControlTypeRole>
                            )

                        // Only include roles that have at least one access control
                        if (Object.keys(accessControlByResource).length === 0) {
                            return null
                        }

                        return { role, accessControlByResource }
                    })
                    .filter(Boolean) as RoleResourceAccessControls[]
            },
        ],

        resources: [
            () => [],
            (): AccessControlType['resource'][] => {
                return [
                    AccessControlResourceType.Action,
                    AccessControlResourceType.Dashboard,
                    AccessControlResourceType.Experiment,
                    AccessControlResourceType.FeatureFlag,
                    AccessControlResourceType.Insight,
                    AccessControlResourceType.Notebook,
                    AccessControlResourceType.RevenueAnalytics,
                    AccessControlResourceType.SessionRecording,
                    AccessControlResourceType.Survey,
                    AccessControlResourceType.SyntheticMonitoring,
                    AccessControlResourceType.WebAnalytics,
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
    afterMount(({ actions }) => {
        actions.loadResourceAccessControls()
    }),
])
