import { actions, afterMount, kea, key, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { AccessLevel, FeatureFlagAssociatedRoleType, RoleType } from '~/types'

import type { featureFlagPermissionsLogicType } from './featureFlagPermissionsLogicType'

interface FeatureFlagPermissionsLogicProps {
    flagId?: number
}

export const featureFlagPermissionsLogic = kea<featureFlagPermissionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagPermissionsLogic']),
    key((props: FeatureFlagPermissionsLogicProps) => `${props.flagId}`),
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
                        feature_flags_access_level: AccessLevel.CUSTOM_ASSIGNED,
                    })
                    return response.results || []
                },
            },
        ],
        associatedRoles: [
            [] as FeatureFlagAssociatedRoleType[],
            {
                loadAssociatedRoles: async () => {
                    if (props.flagId && teamLogic.values.currentTeamId) {
                        const response = await api.resourceAccessPermissions.featureFlags.list(
                            teamLogic.values.currentTeamId,
                            props.flagId
                        )

                        return response.results || []
                    } else {
                        return []
                    }
                },
                addAssociatedRoles: async (flagId?: number) => {
                    const { rolesToAdd } = values
                    const possibleFlagId = props.flagId || flagId
                    if (possibleFlagId && teamLogic.values.currentTeamId) {
                        const newAssociatedRoles = await Promise.all(
                            rolesToAdd.map(
                                async (roleId) =>
                                    await api.resourceAccessPermissions.featureFlags.create(
                                        teamLogic.values.currentTeamId,
                                        possibleFlagId,
                                        roleId
                                    )
                            )
                        )
                        actions.setRolesToAdd([])
                        return [...values.associatedRoles, ...newAssociatedRoles]
                    }
                    return values.associatedRoles
                },
                deleteAssociatedRole: async ({ roleId }) => {
                    const associatedRoleId = values.associatedRoles.find(
                        (associatedRole) => associatedRole.role.id === roleId
                    )?.id
                    if (props.flagId) {
                        associatedRoleId &&
                            (await api.resourceAccessPermissions.featureFlags.delete(
                                teamLogic.values.currentTeamId,
                                props.flagId,
                                associatedRoleId
                            ))
                    }
                    return values.associatedRoles.filter((associatedRole) => associatedRole.id !== associatedRoleId)
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
