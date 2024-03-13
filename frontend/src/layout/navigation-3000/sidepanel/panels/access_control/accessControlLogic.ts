import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlType, AccessControlUpdateType, OrganizationMemberType, RoleType } from '~/types'

import type { accessControlLogicType } from './accessControlLogicType'

export type AccessControlLogicProps = {
    resource: string
    resource_id?: string
}

export const accessControlLogic = kea<accessControlLogicType>([
    props({} as AccessControlLogicProps),
    key((props) => `${props.resource}-${props.resource_id}`),
    path((key) => ['scenes', 'accessControl', 'accessControlLogic', key]),
    connect({
        values: [membersLogic, ['sortedMembers'], teamLogic, ['currentTeam']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        updateAccessControl: (
            accessControl: Pick<AccessControlType, 'access_level' | 'organization_membership' | 'team' | 'role'>
        ) => ({ accessControl }),
        updateAccessControlGlobal: (level: AccessControlType['access_level']) => ({
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

                updateAccessControlGlobal: async ({ level }) => {
                    if (!values.currentTeam) {
                        return values.accessControls
                    }
                    const params: AccessControlUpdateType = {
                        resource: props.resource,
                        resource_id: props.resource_id,
                        team: values.currentTeam.id as any, // Kludge - would be cool if we didn't have this
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
                            role: role as unknown as AccessControlUpdateType['role'], // Kludge - would be cool if we didn't have this
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
                            organization_membership:
                                member as unknown as AccessControlUpdateType['organization_membership'], // Kludge - would be cool if we didn't have this
                            access_level: level,
                        }

                        await api.accessControls.update(params)
                    }

                    return values.accessControls
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
            },
        ],
    })),
    listeners(({ actions }) => ({
        updateAccessControlGlobalSuccess: () => actions.loadAccessControls(),
        updateAccessControlRolesSuccess: () => actions.loadAccessControls(),
        updateAccessControlMembersSuccess: () => actions.loadAccessControls(),
    })),
    selectors({
        accessControlGlobal: [
            (s) => [s.accessControls],
            (accessControls): AccessControlType | null => {
                return accessControls?.find((accessControl) => !!accessControl.team) || null
            },
        ],

        accessControlMembers: [
            (s) => [s.accessControls],
            (accessControls): AccessControlType[] => {
                return (accessControls || []).filter((accessControl) => !!accessControl.organization_membership)
            },
        ],

        accessControlRoles: [
            (s) => [s.accessControls],
            (accessControls): AccessControlType[] => {
                return (accessControls || []).filter((accessControl) => !!accessControl.role)
            },
        ],

        addableRoles: [
            (s) => [s.roles, s.accessControlRoles],
            (roles, accessControlRoles): RoleType[] => {
                return roles ? roles.filter((role) => !accessControlRoles.find((ac) => ac.role?.id === role.id)) : []
            },
        ],

        addableMembers: [
            (s) => [s.sortedMembers, s.accessControlMembers],
            (members, accessControlMembers): any[] => {
                console.log({ members, accessControlMembers })
                return members
                    ? members.filter(
                          (member) => !accessControlMembers.find((ac) => ac.organization_membership?.id === member.id)
                      )
                    : []
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRoles()
        actions.loadAccessControls()
        actions.ensureAllMembersLoaded()
    }),
])
