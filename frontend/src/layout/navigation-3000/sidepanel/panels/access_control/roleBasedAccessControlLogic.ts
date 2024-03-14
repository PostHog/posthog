import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'
import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlType, AccessControlTypeRole, AccessControlUpdateType, RoleType } from '~/types'

import type { roleBasedAccessControlLogicType } from './roleBasedAccessControlLogicType'

export type RoleWithResourceAccessControls = {
    role: RoleType
    accessControlByResource: Record<AccessControlType['resource'], AccessControlTypeRole>
}

export const roleBasedAccessControlLogic = kea<roleBasedAccessControlLogicType>([
    path(['scenes', 'accessControl', 'roleBasedAccessControlLogic']),
    connect({
        values: [membersLogic, ['sortedMembers'], teamLogic, ['currentTeam']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        updateRoleBasedAccessControls: (
            accessControls: Pick<AccessControlUpdateType, 'resource' | 'access_level' | 'role'>[]
        ) => ({ accessControls }),
        selectRole: (role: RoleType | null) => ({ role }),
        removeMemberFromRole: (role: RoleType, member: string) => ({ role, member }),
        addMembersToRole: (role: RoleType, members: string[]) => ({ role, members }),
    }),
    reducers({
        selectedRole: [
            null as RoleType | null,
            {
                selectRole: (_, { role }) => role,
            },
        ],
    }),
    loaders(({ values }) => ({
        roleBasedAccessControls: [
            null as AccessControlTypeRole[] | null,
            {
                loadRoleBasedAccessControls: async () => {
                    const response = await api.accessControls.list({
                        team: values.currentTeam!.id,
                        // TODO: Figure out how to filter down to only the project wide role based controls...
                    })
                    return response.results.filter((accessControl) => !!accessControl.role) as AccessControlTypeRole[]
                },

                updateRoleBasedAccessControls: async ({ accessControls }) => {
                    for (const control of accessControls) {
                        await api.accessControls.update({
                            // team: values.currentTeam!.id,
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
                removeMemberFromRole: async ({ role, member }) => {
                    if (!values.roles) {
                        return null
                    }
                    await api.roles.members.delete(role.id, member)
                    role.members = role.members.filter((roleMember) => roleMember.user.uuid !== member)
                    return [...values.roles]
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        updateRoleBasedAccessControlsSuccess: () => actions.loadRoleBasedAccessControls(),
        loadRolesSuccess: () => {
            if (router.values.hashParams.role) {
                actions.selectRole(values.roles?.find((role) => role.id === router.values.hashParams.role) || null)
            }
        },
    })),

    selectors({
        availableLevels: [
            () => [],
            (): string[] => {
                return ['viewer', 'editor']
            },
        ],
        rolesWithResourceAccessControls: [
            (s) => [s.roles, s.roleBasedAccessControls],
            (roles, accessControls): RoleWithResourceAccessControls[] => {
                if (!roles || !accessControls) {
                    return []
                }

                return roles.map((role) => {
                    const accessControlByResource = accessControls
                        .filter((control) => control.role === role.id)
                        .reduce(
                            (acc, control) => ({
                                ...acc,
                                [control.resource]: control,
                            }),
                            {} as Record<AccessControlType['resource'], AccessControlTypeRole>
                        )

                    return { role, accessControlByResource }
                })
            },
        ],

        resources: [
            () => [],
            (): AccessControlType['resource'][] => {
                // TODO: Sync this as an enum
                return ['feature_flag', 'dashboard', 'insight', 'session_recording']
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRoles()
        actions.loadRoleBasedAccessControls()
        actions.ensureAllMembersLoaded()
    }),

    actionToUrl(({ values }) => ({
        selectRole: () => {
            const { currentLocation } = router.values
            return [
                currentLocation.pathname,
                currentLocation.searchParams,
                {
                    ...currentLocation.hashParams,
                    role: values.selectedRole?.id,
                },
            ]
        },
    })),
])
