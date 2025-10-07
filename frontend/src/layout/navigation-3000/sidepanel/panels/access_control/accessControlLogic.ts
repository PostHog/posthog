import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { LemonSelectOption } from '@posthog/lemon-ui'

import api from 'lib/api'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { toSentenceCase } from 'lib/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlResponseType,
    AccessControlType,
    AccessControlTypeMember,
    AccessControlTypeOrganizationAdmins,
    AccessControlTypeProject,
    AccessControlTypeRole,
    AccessControlUpdateType,
    OrganizationMemberType,
    RoleType,
} from '~/types'

import type { accessControlLogicType } from './accessControlLogicType'
import { roleAccessControlLogic } from './roleAccessControlLogic'
import { ACCESS_LEVEL_ORDER } from './utils'

export type AccessControlLogicProps = {
    resource: APIScopeObject
    resource_id: string
    title: string
    description: string
}

export const accessControlLogic = kea<accessControlLogicType>([
    props({} as AccessControlLogicProps),
    key((props) => `${props.resource}-${props.resource_id}`),
    path((key) => ['scenes', 'accessControl', 'accessControlLogic', key]),
    connect(() => ({
        values: [
            membersLogic,
            ['sortedMembers'],
            teamLogic,
            ['currentTeam'],
            roleAccessControlLogic,
            ['roles'],
            upgradeModalLogic,
            ['guardAvailableFeature'],
        ],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    })),
    actions({
        updateAccessControl: (
            accessControl: Pick<AccessControlType, 'access_level' | 'organization_member' | 'role'>
        ) => ({ accessControl }),
        updateAccessControlDefault: (level: AccessControlLevel) => ({
            level,
        }),
        updateAccessControlRoles: (
            accessControls: {
                role: RoleType['id']
                level: AccessControlLevel | null
            }[]
        ) => ({ accessControls }),
        updateAccessControlMembers: (
            accessControls: {
                member: OrganizationMemberType['id']
                level: AccessControlLevel | null
            }[]
        ) => ({ accessControls }),
    }),
    loaders(({ values }) => ({
        accessControls: [
            null as AccessControlResponseType | null,
            {
                loadAccessControls: async () => {
                    try {
                        const response = await api.get<AccessControlResponseType>(values.endpoint)
                        return response
                    } catch {
                        // Return empty access controls
                        return {
                            access_controls: [],
                            available_access_levels: [
                                AccessControlLevel.None,
                                AccessControlLevel.Viewer,
                                AccessControlLevel.Editor,
                                AccessControlLevel.Manager,
                            ],
                            user_access_level: AccessControlLevel.None,
                            default_access_level: AccessControlLevel.None,
                            user_can_edit_access_levels: false,
                        }
                    }
                },

                updateAccessControlDefault: async ({ level }) => {
                    await api.put<AccessControlType, AccessControlUpdateType>(values.endpoint, {
                        access_level: level,
                    })

                    posthog.capture('access control default access level changed', {
                        resource: values.resource,
                        access_level: level,
                        old_access_level: values.accessControlDefault?.access_level,
                    })

                    return values.accessControls
                },

                updateAccessControlRoles: async ({ accessControls }) => {
                    for (const { role, level } of accessControls) {
                        await api.put<AccessControlType, AccessControlUpdateType>(values.endpoint, {
                            role: role,
                            access_level: level,
                        })

                        const oldAccessControl = values.accessControlRoles.find((ac) => ac.role === role)
                        posthog.capture('access control role access level changed', {
                            resource: values.resource,
                            action: oldAccessControl ? (level === null ? 'removed' : 'changed') : 'added',
                            role: role,
                            access_level: level,
                            old_access_level: oldAccessControl?.access_level,
                        })
                    }

                    return values.accessControls
                },

                updateAccessControlMembers: async ({ accessControls }) => {
                    for (const { member, level } of accessControls) {
                        await api.put<AccessControlType, AccessControlUpdateType>(values.endpoint, {
                            organization_member: member,
                            access_level: level,
                        })

                        const oldAccessControl = values.accessControlMembers.find(
                            (ac) => ac.organization_member === member
                        )
                        posthog.capture('access control member access level changed', {
                            resource: values.resource,
                            action: oldAccessControl ? (level === null ? 'removed' : 'changed') : 'added',
                            member: member,
                            access_level: level,
                            old_access_level: oldAccessControl?.access_level,
                        })
                    }

                    return values.accessControls
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        updateAccessControlDefaultSuccess: () => actions.loadAccessControls(),
        updateAccessControlRolesSuccess: () => actions.loadAccessControls(),
        updateAccessControlMembersSuccess: () => actions.loadAccessControls(),
    })),
    selectors({
        resource: [(_, p) => [p.resource], (resource) => resource],

        endpoint: [
            (_, p) => [p.resource, p.resource_id],
            (resource, resource_id): string => {
                // TODO: This is far from perfect... but it's a start
                if (resource === 'project') {
                    return `api/projects/@current/access_controls`
                }
                return `api/projects/@current/${resource}s/${resource_id}/access_controls`
            },
        ],

        humanReadableResource: [(_, p) => [p.resource], (resource) => resource.replace(/_/g, ' ')],

        minimumAccessLevel: [
            (s) => [s.accessControls],
            (accessControls): AccessControlLevel | null => {
                return accessControls?.minimum_access_level ?? null
            },
        ],

        availableLevelsWithNone: [
            (s) => [s.accessControls],
            (accessControls): AccessControlLevel[] => {
                return accessControls?.available_access_levels ?? []
            },
        ],

        availableLevels: [
            (s) => [s.availableLevelsWithNone],
            (availableLevelsWithNone): AccessControlLevel[] => {
                return availableLevelsWithNone.filter((level) => level !== 'none')
            },
        ],

        canEditAccessControls: [
            (s) => [s.accessControls],
            (accessControls): boolean | null => {
                return accessControls?.user_can_edit_access_levels ?? null
            },
        ],

        accessControlDefaultLevel: [
            (s) => [s.accessControls],
            (accessControls): string | null => {
                return accessControls?.default_access_level ?? null
            },
        ],

        accessControlDefaultOptions: [
            (s) => [s.availableLevelsWithNone, s.minimumAccessLevel, (_, props) => props.resource],
            (availableLevelsWithNone, minimumAccessLevel): LemonSelectOption<string>[] => {
                const options = availableLevelsWithNone.map((level) => {
                    const isDisabled = minimumAccessLevel
                        ? ACCESS_LEVEL_ORDER[level] < ACCESS_LEVEL_ORDER[minimumAccessLevel]
                        : false
                    return {
                        value: level,
                        // TODO: Correct "a" and "an"
                        label: level === 'none' ? 'No access' : toSentenceCase(level),
                        disabledReason: isDisabled ? 'Not available for this resource type' : undefined,
                    }
                })

                return options
            },
        ],

        accessControlDefault: [
            (s) => [s.accessControls, s.accessControlDefaultLevel],
            (accessControls, accessControlDefaultLevel): AccessControlTypeProject => {
                const found = accessControls?.access_controls?.find(
                    (accessControl) => !accessControl.organization_member && !accessControl.role
                ) as AccessControlTypeProject
                return (
                    found ?? {
                        access_level: accessControlDefaultLevel,
                    }
                )
            },
        ],

        organizationAdmins: [
            (s) => [s.sortedMembers],
            (members): OrganizationMemberType[] => {
                return members?.filter((member) => member.level >= OrganizationMembershipLevel.Admin) ?? []
            },
        ],

        organizationAdminsAsAccessControlMember: [
            (s) => [s.organizationAdmins],
            (organizationAdmins): AccessControlTypeOrganizationAdmins => {
                return {
                    organization_admin_members: organizationAdmins.map((member) => member.id),
                    access_level: AccessControlLevel.Admin,
                    created_by: null,
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                    resource: 'organization',
                }
            },
        ],

        accessControlMembers: [
            (s) => [s.accessControls, s.organizationAdminsAsAccessControlMember],
            (
                accessControls,
                organizationAdminsAsAccessControlMember
            ): (AccessControlTypeMember | AccessControlTypeOrganizationAdmins)[] => {
                const members = (accessControls?.access_controls || [])
                    .filter((accessControl) => !!accessControl.organization_member)
                    .filter(
                        (accessControl) =>
                            !organizationAdminsAsAccessControlMember.organization_admin_members.some(
                                (member) => member === accessControl.organization_member
                            )
                    ) as (AccessControlTypeMember | AccessControlTypeOrganizationAdmins)[]
                return members.concat(organizationAdminsAsAccessControlMember)
            },
        ],

        accessControlRoles: [
            (s) => [s.accessControls],
            (accessControls): AccessControlTypeRole[] => {
                return (accessControls?.access_controls || []).filter(
                    (accessControl) => !!accessControl.role
                ) as AccessControlTypeRole[]
            },
        ],

        rolesById: [
            (s) => [s.roles],
            (roles): Record<string, RoleType> => {
                return Object.fromEntries((roles || []).map((role) => [role.id, role]))
            },
        ],

        addableRoles: [
            (s) => [s.roles, s.accessControlRoles],
            (roles, accessControlRoles): RoleType[] => {
                return roles ? roles.filter((role) => !accessControlRoles.find((ac) => ac.role === role.id)) : []
            },
        ],

        membersById: [
            (s) => [s.sortedMembers],
            (members): Record<string, OrganizationMemberType> => {
                return Object.fromEntries((members || []).map((member) => [member.id, member]))
            },
        ],

        addableMembers: [
            (s) => [s.sortedMembers, s.accessControlMembers, s.organizationAdmins],
            (members, accessControlMembers, organizationAdmins): any[] => {
                return members
                    ? members.filter(
                          (member) =>
                              !accessControlMembers.find((ac) => ac.organization_member === member.id) &&
                              !organizationAdmins.find((admin) => admin.id === member.id)
                      )
                    : []
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.ensureAllMembersLoaded()
        actions.loadAccessControls()
    }),
])
