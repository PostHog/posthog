import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { AccessLevel, FeatureFlagAssociatedRoleType, RoleType } from '~/types'

import type { featureFlagPermissionsLogicType } from './featureFlagPermissionsLogicType'

export const featureFlagPermissionsLogic = kea<featureFlagPermissionsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagPermissionsLogic']),
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
    loaders({
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
                    const response = await api.resourceAccessPermissions.featureFlags.list()

                    return response.results || []
                },
            },
        ],
    }),
    selectors({
        addableRoles: [
            (s) => [s.unfilteredAddableRoles],
            (unfilteredAddableRoles): RoleType[] => {
                const addableRoles: RoleType[] = unfilteredAddableRoles
                return addableRoles
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPossibleRolesToAdd()
        actions.loadAssociatedRoles()
    }),
])
