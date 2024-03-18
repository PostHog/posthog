import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    AccessControlType,
    AccessControlTypeMember,
    AccessControlTypeProject,
    AccessControlTypeRole,
    AccessControlUpdateType,
    OrganizationMemberType,
    RoleType,
} from '~/types'

import type { accessControlLogicType } from './accessControlLogicType'
import { roleBasedAccessControlLogic } from './roleBasedAccessControlLogic'

export type AccessControlLogicProps = {
    resource: string
    resource_id: string
}

export const accessControlLogic = kea<accessControlLogicType>([
    props({} as AccessControlLogicProps),
    key((props) => `${props.resource}-${props.resource_id}`),
    path((key) => ['scenes', 'accessControl', 'accessControlLogic', key]),
    connect({
        values: [membersLogic, ['sortedMembers'], teamLogic, ['currentTeam'], roleBasedAccessControlLogic, ['roles']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        updateAccessControl: (
            accessControl: Pick<AccessControlType, 'access_level' | 'organization_member' | 'team' | 'role'>
        ) => ({ accessControl }),
        updateAccessControlProject: (level: AccessControlType['access_level']) => ({
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
    loaders(({ props, values }) => ({
        accessControls: [
            null as AccessControlType[] | null,
            {
                loadAccessControls: async () => {
                    const response = await api.accessControls.list({
                        resource: props.resource,
                        resource_id: props.resource_id,
                    })
                    return response?.results || []
                },

                updateAccessControlProject: async ({ level }) => {
                    if (!values.currentTeam) {
                        return values.accessControls
                    }
                    const params: AccessControlUpdateType = {
                        resource: props.resource,
                        resource_id: props.resource_id,
                        team: values.currentTeam.id,
                        access_level: level,
                    }

                    await api.accessControls.update(params)

                    return values.accessControls
                },

                updateAccessControlRoles: async ({ accessControls }) => {
                    for (const { role, level } of accessControls) {
                        const params: AccessControlUpdateType = {
                            resource: props.resource,
                            resource_id: props.resource_id,
                            role: role,
                            access_level: level,
                        }

                        await api.accessControls.update(params)
                    }

                    return values.accessControls
                },

                updateAccessControlMembers: async ({ accessControls }) => {
                    for (const { member, level } of accessControls) {
                        const params: AccessControlUpdateType = {
                            resource: props.resource,
                            resource_id: props.resource_id,
                            organization_member: member,
                            access_level: level,
                        }

                        await api.accessControls.update(params)
                    }

                    return values.accessControls
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        updateAccessControlProjectSuccess: () => actions.loadAccessControls(),
        updateAccessControlRolesSuccess: () => actions.loadAccessControls(),
        updateAccessControlMembersSuccess: () => actions.loadAccessControls(),
    })),
    selectors({
        availableLevels: [
            () => [(_, props) => props],
            (props): AccessControlTypeProject['access_level'][] => {
                if (!props.resource) {
                    return []
                }

                if (props.resource === 'project') {
                    return ['member', 'admin']
                }

                return ['viewer', 'editor']
            },
        ],
        accessControlProject: [
            (s) => [s.accessControls],
            (accessControls): AccessControlTypeProject | null => {
                return (
                    (accessControls?.find((accessControl) => !!accessControl.team) as AccessControlTypeProject) || null
                )
            },
        ],

        accessControlMembers: [
            (s) => [s.accessControls],
            (accessControls): AccessControlTypeMember[] => {
                return (accessControls || []).filter(
                    (accessControl) => !!accessControl.organization_member
                ) as AccessControlTypeMember[]
            },
        ],

        accessControlRoles: [
            (s) => [s.accessControls],
            (accessControls): AccessControlTypeRole[] => {
                return (accessControls || []).filter((accessControl) => !!accessControl.role) as AccessControlTypeRole[]
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
    }),
    afterMount(({ actions }) => {
        actions.loadAccessControls()
        actions.ensureAllMembersLoaded()
    }),
])
