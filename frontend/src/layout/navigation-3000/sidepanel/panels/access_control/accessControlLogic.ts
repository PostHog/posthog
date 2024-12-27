import { LemonSelectOption } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { toSentenceCase } from 'lib/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    AccessControlResponseType,
    AccessControlType,
    AccessControlTypeMember,
    AccessControlTypeProject,
    AccessControlTypeRole,
    AccessControlUpdateType,
    APIScopeObject,
    OrganizationMemberType,
    RoleType,
    WithAccessControl,
} from '~/types'

import type { accessControlLogicType } from './accessControlLogicType'
import { roleBasedAccessControlLogic } from './roleBasedAccessControlLogic'

export type AccessControlLogicProps = {
    resource: APIScopeObject
    resource_id: string
}

export const accessControlLogic = kea<accessControlLogicType>([
    props({} as AccessControlLogicProps),
    key((props) => `${props.resource}-${props.resource_id}`),
    path((key) => ['scenes', 'accessControl', 'accessControlLogic', key]),
    connect({
        values: [
            membersLogic,
            ['sortedMembers'],
            teamLogic,
            ['currentTeam'],
            roleBasedAccessControlLogic,
            ['roles'],
            upgradeModalLogic,
            ['guardAvailableFeature'],
        ],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        updateAccessControl: (
            accessControl: Pick<AccessControlType, 'access_level' | 'organization_member' | 'role'>
        ) => ({ accessControl }),
        updateAccessControlDefault: (level: AccessControlType['access_level']) => ({
            level,
        }),
        updateAccessControlRoles: (
            accessControls: {
                role: RoleType['id']
                level: AccessControlType['access_level']
            }[]
        ) => ({ accessControls }),
        updateAccessControlMembers: (
            accessControls: {
                member: OrganizationMemberType['id']
                level: AccessControlType['access_level']
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
                    } catch (error) {
                        // Return empty access controls
                        return {
                            access_controls: [],
                            available_access_levels: ['none', 'viewer', 'editor'],
                            user_access_level: 'none',
                            default_access_level: 'none',
                            user_can_edit_access_levels: false,
                        }
                    }
                },

                updateAccessControlDefault: async ({ level }) => {
                    await api.put<AccessControlType, AccessControlUpdateType>(values.endpoint, {
                        access_level: level,
                    })

                    return values.accessControls
                },

                updateAccessControlRoles: async ({ accessControls }) => {
                    for (const { role, level } of accessControls) {
                        await api.put<AccessControlType, AccessControlUpdateType>(values.endpoint, {
                            role: role,
                            access_level: level,
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
        endpoint: [
            () => [(_, props) => props],
            (props): string => {
                // TODO: This is far from perfect... but it's a start
                if (props.resource === 'project') {
                    return `api/projects/@current/access_controls`
                }
                return `api/projects/@current/${props.resource}s/${props.resource_id}/access_controls`
            },
        ],
        humanReadableResource: [
            () => [(_, props) => props],
            (props): string => {
                return props.resource.replace(/_/g, ' ')
            },
        ],

        availableLevelsWithNone: [
            (s) => [s.accessControls],
            (accessControls): string[] => {
                return accessControls?.available_access_levels ?? []
            },
        ],

        availableLevels: [
            (s) => [s.availableLevelsWithNone],
            (availableLevelsWithNone): string[] => {
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
            (s) => [s.availableLevelsWithNone, (_, props) => props.resource],
            (availableLevelsWithNone): LemonSelectOption<string>[] => {
                const options = availableLevelsWithNone.map((level) => ({
                    value: level,
                    // TODO: Correct "a" and "an"
                    label: level === 'none' ? 'No access' : toSentenceCase(level),
                }))

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

        accessControlMembers: [
            (s) => [s.accessControls],
            (accessControls): AccessControlTypeMember[] => {
                return (accessControls?.access_controls || []).filter(
                    (accessControl) => !!accessControl.organization_member
                ) as AccessControlTypeMember[]
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
            (s) => [s.sortedMembers, s.accessControlMembers],
            (members, accessControlMembers): any[] => {
                return members
                    ? members.filter(
                          (member) => !accessControlMembers.find((ac) => ac.organization_member === member.id)
                      )
                    : []
            },
        ],

        hasResourceAccess: [
            () => [],
            () =>
                ({
                    userAccessLevel,
                    requiredLevels,
                }: {
                    userAccessLevel?: WithAccessControl['user_access_level']
                    requiredLevels: WithAccessControl['user_access_level'][]
                }) => {
                    // Fallback to true if userAccessLevel is not set
                    return userAccessLevel ? requiredLevels.includes(userAccessLevel) : true
                },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadAccessControls()
        actions.ensureAllMembersLoaded()
    }),
])
