import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { AccessLevel, FeatureFlagAssociatedRoleType, Resource, RoleType } from '~/types'

import type { featureFlagPermissionsLogicType } from './featureFlagPermissionsLogicType'

export type FeatureFlagPermissionsLogicProps = {
    flagId: number | null
}

export const featureFlagPermissionsLogic = kea<featureFlagPermissionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagPermissionsLogic']),
    props({} as FeatureFlagPermissionsLogicProps),
    key((props: FeatureFlagPermissionsLogicProps) => `${props.flagId}`),
    connect({ values: [rolesLogic, ['roles']] }),
    actions({
        setModalOpen: (visible: boolean) => ({ visible }),
        setRolesToAdd: (roleIds: string[]) => ({ roleIds }),
    }),
    reducers({
        permissionModalVisible: [
            false,
            {
                setModalOpen: (_, { visible }) => visible,
            },
        ],
        rolesToAdd: [
            [] as string[],
            {
                setRolesToAdd: (_, { roleIds }) => roleIds,
            },
        ],
    }),
    loaders(({ props, values, actions }) => ({
        unfilteredAddableRoles: [
            [] as RoleType[],
            {
                loadPossibleRolesToAdd: async () => {
                    const response = await api.roles.list({
                        feature_flags_access_level: AccessLevel.READ,
                    })
                    return response.results || []
                },
            },
        ],
        associatedRoles: [
            [] as FeatureFlagAssociatedRoleType[],
            {
                loadAssociatedRoles: async () => {
                    if (props.flagId) {
                        const response = await api.resourceAccessPermissions.featureFlags.list(props.flagId)

                        return response.results || []
                    } else {
                        return []
                    }
                },
                addAssociatedRoles: async (flagId?: number) => {
                    const { rolesToAdd } = values
                    const possibleFlagId = props.flagId || flagId
                    if (possibleFlagId) {
                        const newAssociatedRoles = await Promise.all(
                            rolesToAdd.map(
                                async (roleId) =>
                                    await api.resourceAccessPermissions.featureFlags.create(possibleFlagId, roleId)
                            )
                        )
                        actions.setRolesToAdd([])
                        return [...values.associatedRoles, ...newAssociatedRoles]
                    }
                    const newFlagAssociatedRoles: RoleType[] = []
                    for (const roleId of rolesToAdd) {
                        const existingRole = values.roles.find((r) => roleId === r.id)
                        if (existingRole?.id) {
                            newFlagAssociatedRoles.push(existingRole)
                        }
                    }
                    eventUsageLogic.actions.reportRoleCustomAddedToAResource(Resource.FEATURE_FLAGS, rolesToAdd.length)
                    return newFlagAssociatedRoles.map((newRole) => ({
                        id: newRole.id,
                        role: newRole,
                        feature_flag: null,
                        updated_at: '',
                        added_at: '',
                    }))
                },
                deleteAssociatedRole: async ({ roleId }) => {
                    const associatedRoleId = values.associatedRoles.find(
                        (associatedRole) => associatedRole.role.id === roleId
                    )?.id
                    const filteredRoles = values.associatedRoles.filter(
                        (associatedRole) => associatedRole.id !== associatedRoleId
                    )

                    if (props.flagId) {
                        associatedRoleId &&
                            (await api.resourceAccessPermissions.featureFlags.delete(props.flagId, associatedRoleId))
                    } else {
                        actions.setRolesToAdd(filteredRoles.map((filteredRole) => filteredRole.id))
                    }
                    return filteredRoles
                },
            },
        ],
    })),
    selectors({
        derivedRoles: [
            (s) => [s.associatedRoles],
            (associatedRoles): RoleType[] => {
                return associatedRoles.map((associatedRole: FeatureFlagAssociatedRoleType) => associatedRole.role)
            },
        ],
        addableRoles: [
            (s) => [s.unfilteredAddableRoles, s.associatedRoles],
            (unfilteredAddableRoles, associatedRoles): RoleType[] => {
                const addableRoles: RoleType[] = []

                for (const role of unfilteredAddableRoles) {
                    if (
                        !associatedRoles.some(
                            (associatedRole: FeatureFlagAssociatedRoleType) => associatedRole.role.id === role.id
                        )
                    ) {
                        addableRoles.push(role)
                    }
                }

                return addableRoles
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPossibleRolesToAdd()
        actions.loadAssociatedRoles()
    }),
])
