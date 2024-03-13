import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlType, RoleType } from '~/types'

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
    }),
    actions({
        updateAccessControl: (
            accessControl: Pick<AccessControlType, 'access_level' | 'organization_membership' | 'team' | 'role'>
        ) => ({ accessControl }),
        updateAccessControlGlobal: (level: AccessControlType['access_level']) => ({
            level,
        }),
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
                    const params = {
                        resource: props.resource,
                        resource_id: props.resource_id,
                        ...accessControl,
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
    listeners(({ actions, values }) => ({
        updateAccessControlGlobal: ({ level }) => {
            if (!values.currentTeam) {
                return
            }
            const accessControl = {
                access_level: level,
            }

            actions.updateAccessControl(accessControl)
        },
    })),
    selectors({
        accessControlGlobal: [
            (s) => [s.accessControls],
            (accessControls): AccessControlType | null => {
                return (
                    accessControls?.find(
                        (accessControl) => !accessControl.organization_membership && !accessControl.role
                    ) || null
                )
            },
        ],

        accessControlUsers: [
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
    }),
    afterMount(({ actions }) => {
        actions.loadRoles()
        actions.loadAccessControls()
    }),
])
