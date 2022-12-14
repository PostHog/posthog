import { afterMount, kea, selectors, path, connect, actions, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { OrganizationResourcePermissionType, Resource, AccessLevel, RoleType } from '~/types'
import type { permissionsLogicType } from './permissionsLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { rolesLogic } from './Roles/rolesLogic'
import { lemonToast } from '@posthog/lemon-ui'

const ResourceDisplayMapping: Record<Resource, string> = {
    [Resource.FEATURE_FLAGS]: 'Feature Flags',
}

export const ResourcePermissionMapping: Record<AccessLevel, string> = {
    [AccessLevel.WRITE]: 'View & Edit',
    [AccessLevel.READ]: 'View Only',
}

export interface FormattedResourceLevel {
    id: string | null
    resource: Resource
    name: string
    access_level: AccessLevel
}

const ResourceAccessLevelMapping: Record<Resource, string> = {
    [Resource.FEATURE_FLAGS]: 'feature_flags_access_level',
}

export const permissionsLogic = kea<permissionsLogicType>([
    path(['scenes', 'organization', 'Settings', 'Permissions', 'permissionsLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], rolesLogic, ['roles']],
        actions: [rolesLogic, ['updateRole']],
    }),
    actions({
        updatePermission: (
            checked: boolean,
            role: RoleType,
            resourceId: OrganizationResourcePermissionType['id'] | null,
            resourceType: Resource
        ) => ({ checked, role, resourceId, resourceType }),
    }),
    loaders(({ values }) => ({
        organizationResourcePermissions: [
            [] as OrganizationResourcePermissionType[],
            {
                loadOrganizationResourcePermissions: async () => {
                    const response = await api.resourcePermissions.list()
                    return response?.results || []
                },
                updateOrganizationResourcePermission: async ({ id, resource, access_level }) => {
                    if (id) {
                        const response = await api.resourcePermissions.update(id, { access_level: access_level })
                        return values.organizationResourcePermissions.map((permission) =>
                            permission.id == response.id ? response : permission
                        )
                    } else {
                        const response = await api.resourcePermissions.create({
                            resource: resource,
                            access_level: access_level,
                        })
                        return [...values.organizationResourcePermissions, response]
                    }
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        updatePermission: async ({ checked, role, resourceId, resourceType }) => {
            const accessLevel = checked ? AccessLevel.WRITE : AccessLevel.READ
            if (role.id) {
                const updatedRole = await api.roles.update(role.id, {
                    [ResourceAccessLevelMapping[resourceType]]: accessLevel,
                })
                if (updatedRole) {
                    actions.updateRole(updatedRole)
                    lemonToast.success(`${role.name} edit access updated`)
                }
            } else {
                actions.updateOrganizationResourcePermission({
                    id: resourceId,
                    access_level: accessLevel,
                })
            }
        },
        updateOrganizationResourcePermissionSuccess: () => {
            lemonToast.success('Organizational edit access updated')
        },
    })),
    selectors({
        organizationResourcePermissionsMap: [
            (s) => [s.organizationResourcePermissions],
            (organizationResourcePermissions: OrganizationResourcePermissionType[]) => {
                return organizationResourcePermissions.reduce(
                    (obj, resourcePermission: OrganizationResourcePermissionType) => ({
                        ...obj,
                        [resourcePermission.resource]: resourcePermission,
                    }),
                    {}
                )
            },
        ],
        allPermissions: [
            (s) => [s.organizationResourcePermissionsMap],
            (
                organizationResourcePermissionsMap: Record<Resource, OrganizationResourcePermissionType>
            ): FormattedResourceLevel[] => {
                return Object.keys(ResourceDisplayMapping).map(
                    (key) =>
                        ({
                            id: organizationResourcePermissionsMap[key]?.id || null,
                            resource: key,
                            name: ResourceDisplayMapping[key],
                            access_level: organizationResourcePermissionsMap[key]?.access_level || AccessLevel.WRITE,
                        } as FormattedResourceLevel)
                )
            },
        ],
        shouldShowPermissionsTable: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.ROLE_BASED_ACCESS] === 'control',
        ],
        resourceRolesAccess: [
            (s) => [s.allPermissions, s.roles],
            (permissions, roles) => {
                const resources = permissions.map((resource) => ({
                    [resource.resource]: {
                        organization_default: resource.access_level,
                        id: resource.id,
                    },
                }))
                for (const role of roles) {
                    for (const source of resources) {
                        const resourceType = Object.keys(source)[0]
                        source[resourceType][`${role.name}`] = role[ResourceAccessLevelMapping[resourceType]]
                    }
                }
                return resources
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadOrganizationResourcePermissions()
    }),
])
