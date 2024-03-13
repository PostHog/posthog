import { actions, afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TeamMembershipLevel } from 'lib/constants'
import { membersLogic } from 'scenes/organization/membersLogic'

import { AccessControlType, AccessLevel, Resource, RoleMemberType, RoleType } from '~/types'

import type { accessControlLogicType } from './accessControlLogicType'

export type AccessControlLogicProps = {
    resource: string
    resource_id?: string
}

export type RoleWithAccess = {
    role: RoleType
    level: TeamMembershipLevel
}

export const accessControlLogic = kea<accessControlLogicType>([
    props({} as AccessControlLogicProps),
    key((props) => `${props.resource}-${props.resource_id}`),
    path((key) => ['scenes', 'accessControl', 'accessControlLogic', key]),
    connect({
        values: [membersLogic, ['sortedMembers']],
    }),
    actions({
        updateAccessControl: (
            accessControl: Pick<AccessControlType, 'access_level' | 'organization_membership' | 'team' | 'role'>
        ) => ({ accessControl }),
    }),
    loaders(({ props }) => ({
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

                updateAccessControl: async ({ accessControl }) => {
                    console.log('accessControl', accessControl)
                    const params = {
                        resource: props.resource,
                        resource_id: props.resource_id,
                    }

                    const response = await api.accessControls.update(params)
                    return response?.results || []
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
    selectors({
        rolesWithAccess: [
            (s) => [s.roles],
            (roles): RoleWithAccess[] => {
                return (roles || [])?.map((role) => {
                    return {
                        role,
                        level: TeamMembershipLevel.Member,
                    }
                })
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRoles()
        actions.loadAccessControls()
    }),
])
