import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { resourcesAccessControlLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/resourcesAccessControlLogic'
import { roleAccessControlLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/roleAccessControlLogic'
import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlResponseType,
    AccessControlType,
    AccessControlTypeRole,
    OrganizationMemberType,
    ProjectBasicType,
    RoleType,
} from '~/types'

import type { memberAccessModalLogicType } from './memberAccessModalLogicType'

export interface MemberAccessModalLogicProps {
    member: OrganizationMemberType | null
}

export interface MemberProjectAccess {
    project: ProjectBasicType
    accessLevel: AccessControlLevel | null
}

export interface MemberResourceOverride {
    resource: APIScopeObject
    resourceId: string
    resourceName: string
    accessLevel: AccessControlLevel
}

export const memberAccessModalLogic = kea<memberAccessModalLogicType>([
    props({} as MemberAccessModalLogicProps),
    key((props) => props.member?.user.uuid ?? 'new'),
    path((key) => ['scenes', 'settings', 'organization', 'memberAccessModalLogic', key]),
    connect(() => ({
        values: [
            membersLogic,
            ['members'],
            organizationLogic,
            ['currentOrganization'],
            teamLogic,
            ['currentTeam'],
            userLogic,
            ['user'],
            roleAccessControlLogic,
            ['roles'],
            resourcesAccessControlLogic,
            ['resourceAccessControls', 'resources'],
        ],
        actions: [
            membersLogic,
            ['changeMemberAccessLevel', 'removeMember', 'loadMemberScopedApiKeys'],
            organizationLogic,
            ['loadCurrentOrganization'],
        ],
    })),
    actions({
        openModal: (member: OrganizationMemberType) => ({ member }),
        closeModal: true,
        setMemberLevel: (level: OrganizationMembershipLevel) => ({ level }),
        setMemberRoles: (roleIds: string[]) => ({ roleIds }),
        updateProjectAccess: (projectId: number, level: AccessControlLevel | null) => ({ projectId, level }),
        updateResourceAccess: (resource: APIScopeObject, level: AccessControlLevel | null) => ({ resource, level }),
        saveChanges: true,
    }),
    reducers({
        modalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        selectedMember: [
            null as OrganizationMemberType | null,
            {
                openModal: (_, { member }) => member,
                closeModal: () => null,
            },
        ],
        pendingLevelChange: [
            null as OrganizationMembershipLevel | null,
            {
                openModal: () => null,
                setMemberLevel: (_, { level }) => level,
                closeModal: () => null,
            },
        ],
        pendingRoleChanges: [
            null as string[] | null,
            {
                openModal: () => null,
                setMemberRoles: (_, { roleIds }) => roleIds,
                closeModal: () => null,
            },
        ],
        pendingProjectAccessChanges: [
            {} as Record<number, AccessControlLevel | null>,
            {
                openModal: () => ({}),
                updateProjectAccess: (state, { projectId, level }) => ({ ...state, [projectId]: level }),
                closeModal: () => ({}),
            },
        ],
        pendingResourceAccessChanges: [
            {} as Record<APIScopeObject, AccessControlLevel | null>,
            {
                openModal: () => ({}) as Record<APIScopeObject, AccessControlLevel | null>,
                updateResourceAccess: (state, { resource, level }) => ({ ...state, [resource]: level }),
                closeModal: () => ({}) as Record<APIScopeObject, AccessControlLevel | null>,
            },
        ],
    }),
    loaders(({ values }) => ({
        memberAccessDetails: [
            null as {
                projectAccess: Record<number, AccessControlLevel>
                resourceAccess: Record<APIScopeObject, AccessControlTypeRole>
                resourceOverrides: MemberResourceOverride[]
            } | null,
            {
                loadMemberAccessDetails: async () => {
                    if (!values.selectedMember) {
                        return null
                    }

                    // Load resource access controls for this member
                    const resourceAccessControls = await api.get<AccessControlResponseType>(
                        'api/projects/@current/resource_access_controls'
                    )

                    // Filter to just this member's access controls
                    const memberAccessControls = (resourceAccessControls?.access_controls ?? []).filter(
                        (control: AccessControlType) => control.organization_member === values.selectedMember?.id
                    )

                    const resourceAccess: Record<APIScopeObject, AccessControlTypeRole> = {}
                    for (const control of memberAccessControls) {
                        resourceAccess[control.resource as APIScopeObject] = control as AccessControlTypeRole
                    }

                    // Load project access for all projects
                    const projectAccess: Record<number, AccessControlLevel> = {}
                    const projects = values.currentOrganization?.projects ?? []

                    for (const project of projects) {
                        try {
                            const projectAccessControls = await api.get<AccessControlResponseType>(
                                `api/projects/${project.id}/access_controls`
                            )
                            const memberProjectControl = projectAccessControls?.access_controls?.find(
                                (control: AccessControlType) =>
                                    control.organization_member === values.selectedMember?.id
                            )
                            if (memberProjectControl?.access_level) {
                                projectAccess[project.id] = memberProjectControl.access_level
                            }
                        } catch {
                            // Ignore errors for projects the user can't access
                        }
                    }

                    return {
                        projectAccess,
                        resourceAccess,
                        resourceOverrides: [], // TODO: Load object-level overrides
                    }
                },
            },
        ],
    })),
    selectors({
        member: [(_, p) => [p.member], (member) => member],

        memberLevel: [
            (s) => [s.selectedMember, s.pendingLevelChange],
            (member, pendingChange): OrganizationMembershipLevel => {
                if (pendingChange !== null) {
                    return pendingChange
                }
                return member?.level ?? OrganizationMembershipLevel.Member
            },
        ],

        memberLevelName: [(s) => [s.memberLevel], (level): string => membershipLevelToName.get(level) ?? 'member'],

        isOwnerOrAdmin: [
            (s) => [s.memberLevel],
            (level): boolean =>
                level === OrganizationMembershipLevel.Owner || level === OrganizationMembershipLevel.Admin,
        ],

        memberRoles: [
            (s) => [s.selectedMember, s.roles, s.pendingRoleChanges],
            (member, roles, pendingChanges): RoleType[] => {
                if (!member || !roles) {
                    return []
                }

                // If there are pending changes, use those
                if (pendingChanges !== null) {
                    return roles.filter((role) => pendingChanges.includes(role.id))
                }

                // Otherwise, find roles that include this member
                return roles.filter((role) =>
                    role.members.some((roleMember) => roleMember.user.uuid === member.user.uuid)
                )
            },
        ],

        memberRoleIds: [(s) => [s.memberRoles], (roles): string[] => roles.map((role) => role.id)],

        projects: [(s) => [s.currentOrganization], (org): ProjectBasicType[] => org?.projects ?? []],

        memberProjectAccess: [
            (s) => [s.projects, s.memberAccessDetails, s.pendingProjectAccessChanges],
            (projects, accessDetails, pendingChanges): MemberProjectAccess[] => {
                return projects.map((project) => ({
                    project,
                    accessLevel:
                        pendingChanges[project.id] !== undefined
                            ? pendingChanges[project.id]
                            : (accessDetails?.projectAccess[project.id] ?? null),
                }))
            },
        ],

        memberResourceAccess: [
            (s) => [s.resources, s.memberAccessDetails, s.pendingResourceAccessChanges],
            (resources, accessDetails, pendingChanges): Record<APIScopeObject, AccessControlLevel | null> => {
                const result: Record<APIScopeObject, AccessControlLevel | null> = {} as Record<
                    APIScopeObject,
                    AccessControlLevel | null
                >
                for (const resource of resources) {
                    result[resource] =
                        pendingChanges[resource] !== undefined
                            ? pendingChanges[resource]
                            : (accessDetails?.resourceAccess[resource]?.access_level ?? null)
                }
                return result
            },
        ],

        memberResourceOverrides: [
            (s) => [s.memberAccessDetails],
            (accessDetails): MemberResourceOverride[] => accessDetails?.resourceOverrides ?? [],
        ],

        hasUnsavedChanges: [
            (s) => [
                s.pendingLevelChange,
                s.pendingRoleChanges,
                s.pendingProjectAccessChanges,
                s.pendingResourceAccessChanges,
            ],
            (levelChange, roleChanges, projectChanges, resourceChanges): boolean => {
                return (
                    levelChange !== null ||
                    roleChanges !== null ||
                    Object.keys(projectChanges).length > 0 ||
                    Object.keys(resourceChanges).length > 0
                )
            },
        ],

        canEditMember: [
            (s) => [s.user, s.selectedMember, s.currentOrganization],
            (user, member, org): boolean => {
                if (!user || !member || !org?.membership_level) {
                    return false
                }
                // Can't edit yourself
                if (user.uuid === member.user.uuid) {
                    return false
                }
                // Owners can edit anyone except other owners
                if (org.membership_level === OrganizationMembershipLevel.Owner) {
                    return member.level !== OrganizationMembershipLevel.Owner
                }
                // Admins can edit members with lower or equal level
                if (org.membership_level === OrganizationMembershipLevel.Admin) {
                    return member.level <= org.membership_level
                }
                return false
            },
        ],

        levelDescription: [
            (s) => [s.memberLevel],
            (level): string => {
                switch (level) {
                    case OrganizationMembershipLevel.Owner:
                        return 'Owners have full control over the organization, including billing and member management. They have admin access to all projects.'
                    case OrganizationMembershipLevel.Admin:
                        return 'Admins can manage organization settings and members. They have admin access to all projects.'
                    case OrganizationMembershipLevel.Member:
                        return 'Members have access based on their project-specific permissions and roles.'
                    default:
                        return ''
                }
            },
        ],

        projectAccessSummary: [
            (s) => [s.memberProjectAccess, s.isOwnerOrAdmin],
            (projectAccess, isOwnerOrAdmin): string => {
                if (isOwnerOrAdmin) {
                    return 'All projects'
                }
                const accessibleProjects = projectAccess.filter((pa) => pa.accessLevel !== null)
                if (accessibleProjects.length === 0) {
                    return 'No projects'
                }
                if (accessibleProjects.length === projectAccess.length) {
                    return 'All projects'
                }
                const firstTwo = accessibleProjects.slice(0, 2).map((pa) => pa.project.name)
                if (accessibleProjects.length > 2) {
                    return `${firstTwo.join(', ')} +${accessibleProjects.length - 2}`
                }
                return firstTwo.join(', ')
            },
        ],

        featureAccessSummary: [
            (s) => [s.memberResourceAccess, s.isOwnerOrAdmin],
            (resourceAccess, isOwnerOrAdmin): string => {
                if (isOwnerOrAdmin) {
                    return 'All features'
                }
                const restrictedCount = Object.values(resourceAccess).filter(
                    (level) => level !== null && level !== AccessControlLevel.None
                ).length
                if (restrictedCount === 0) {
                    return 'Default access'
                }
                return `${restrictedCount} overrides`
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        openModal: () => {
            actions.loadMemberAccessDetails()
        },

        saveChanges: async () => {
            if (!values.selectedMember) {
                return
            }

            try {
                // Save level change
                if (values.pendingLevelChange !== null) {
                    await actions.changeMemberAccessLevel(values.selectedMember, values.pendingLevelChange)
                }

                // Save role changes
                if (values.pendingRoleChanges !== null) {
                    const currentRoleIds = values.roles
                        .filter((role) => role.members.some((m) => m.user.uuid === values.selectedMember?.user.uuid))
                        .map((r) => r.id)

                    // Add to new roles
                    for (const roleId of values.pendingRoleChanges) {
                        if (!currentRoleIds.includes(roleId)) {
                            const role = values.roles.find((r) => r.id === roleId)
                            if (role) {
                                await api.roles.members.create(roleId, values.selectedMember.user.uuid)
                            }
                        }
                    }

                    // Remove from old roles
                    for (const roleId of currentRoleIds) {
                        if (!values.pendingRoleChanges.includes(roleId)) {
                            const role = values.roles.find((r) => r.id === roleId)
                            const roleMember = role?.members.find(
                                (m) => m.user.uuid === values.selectedMember?.user.uuid
                            )
                            if (roleMember) {
                                await api.roles.members.delete(roleId, roleMember.id)
                            }
                        }
                    }
                }

                // Save project access changes
                for (const [projectIdStr, level] of Object.entries(values.pendingProjectAccessChanges)) {
                    const projectId = parseInt(projectIdStr)
                    await api.put(`api/projects/${projectId}/access_controls`, {
                        organization_member: values.selectedMember.id,
                        access_level: level,
                    })
                }

                // Save resource access changes
                for (const [resource, level] of Object.entries(values.pendingResourceAccessChanges)) {
                    await api.put('api/projects/@current/resource_access_controls', {
                        organization_member: values.selectedMember.id,
                        resource,
                        access_level: level,
                    })
                }

                lemonToast.success('Member access updated successfully')
                actions.loadCurrentOrganization()
                actions.closeModal()
            } catch {
                lemonToast.error('Failed to update member access')
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.member) {
            actions.openModal(props.member)
        }
    }),
])
