import { afterMount, kea, selectors, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { OrganizationResourcePermissionType, Resource, AccessLevel } from '~/types'
import { permissionsLogicType } from './permissionsLogicType'

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

export const permissionsLogic = kea<permissionsLogicType>([
    path(['scenes', 'organization', 'Settings', 'Permissions', 'permissionsLogic']),
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
    }),
    afterMount(({ actions }) => {
        actions.loadOrganizationResourcePermissions()
    }),
])
