import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    AccessControlDefaultsResponseApi,
    AccessControlMembersResponseApi,
    AccessControlObjectRulesResponseApi,
    AccessControlPropertyRulesResponseApi,
    AccessControlRolesResponseApi,
    EnvironmentsAccessControlMemberObjectsRetrieveParams,
    EnvironmentsAccessControlMemberPropertiesRetrieveParams,
    EnvironmentsAccessControlMembersRetrieveParams,
    EnvironmentsAccessControlRoleObjectsRetrieveParams,
    EnvironmentsAccessControlRolePropertiesRetrieveParams,
    EnvironmentsAccessControlRolesRetrieveParams,
    OrganizationsProjectsAccessControlMemberObjectsRetrieveParams,
    OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams,
    OrganizationsProjectsAccessControlMembersRetrieveParams,
    OrganizationsProjectsAccessControlRoleObjectsRetrieveParams,
    OrganizationsProjectsAccessControlRolePropertiesRetrieveParams,
    OrganizationsProjectsAccessControlRolesRetrieveParams,
    PropertyAccessControlRuleApi,
    PropertyAccessControlStateApi,
    PropertyAccessControlUpdateApi,
    PropertyAccessControlsDestroyParams,
    PropertyAccessControlsRetrieveParams,
} from './api.schemas'

export const getOrganizationsProjectsAccessControlDefaultObjectsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_default_objects/`
}

/**
 * Object rules that apply to everyone without a rule of their own on that object.
 */
export const organizationsProjectsAccessControlDefaultObjectsRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<AccessControlObjectRulesResponseApi> => {
    return apiMutator<AccessControlObjectRulesResponseApi>(
        getOrganizationsProjectsAccessControlDefaultObjectsRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlDefaultPropertiesRetrieveUrl = (
    organizationId: string,
    id: number
) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_default_properties/`
}

/**
 * Property rules that apply to everyone without a rule of their own on that property.
 */
export const organizationsProjectsAccessControlDefaultPropertiesRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<AccessControlPropertyRulesResponseApi> => {
    return apiMutator<AccessControlPropertyRulesResponseApi>(
        getOrganizationsProjectsAccessControlDefaultPropertiesRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlDefaultsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_defaults/`
}

/**
 * The project's default access: the level everyone without a rule of their own gets for the project and for each resource type, plus the resource types that accept rules on single objects.
 */
export const organizationsProjectsAccessControlDefaultsRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<AccessControlDefaultsResponseApi> => {
    return apiMutator<AccessControlDefaultsResponseApi>(
        getOrganizationsProjectsAccessControlDefaultsRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlMemberObjectsRetrieveUrl = (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlMemberObjectsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/access_control_member_objects/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/access_control_member_objects/`
}

/**
 * Object rules configured for one member: the dashboards, insights, notebooks and other single objects the member is granted or denied, regardless of the resource-level rules.
 */
export const organizationsProjectsAccessControlMemberObjectsRetrieve = async (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlMemberObjectsRetrieveParams,
    options?: RequestInit
): Promise<AccessControlObjectRulesResponseApi> => {
    return apiMutator<AccessControlObjectRulesResponseApi>(
        getOrganizationsProjectsAccessControlMemberObjectsRetrieveUrl(organizationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlMemberPropertiesRetrieveUrl = (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/access_control_member_properties/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/access_control_member_properties/`
}

/**
 * Property rules configured for one member: the person and event properties the member can read, read and write, or not see.
 */
export const organizationsProjectsAccessControlMemberPropertiesRetrieve = async (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams,
    options?: RequestInit
): Promise<AccessControlPropertyRulesResponseApi> => {
    return apiMutator<AccessControlPropertyRulesResponseApi>(
        getOrganizationsProjectsAccessControlMemberPropertiesRetrieveUrl(organizationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlMembersRetrieveUrl = (
    organizationId: string,
    id: number,
    params?: OrganizationsProjectsAccessControlMembersRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/access_control_members/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/access_control_members/`
}

/**
 * Every organization member's resolved access to this project and to each resource type in it: the member's own rule, the level that is enforced, and the rule the enforced level comes from (their own, a role's, the project default, or an org-admin bypass). Pass `member_id` for one member.
 */
export const organizationsProjectsAccessControlMembersRetrieve = async (
    organizationId: string,
    id: number,
    params?: OrganizationsProjectsAccessControlMembersRetrieveParams,
    options?: RequestInit
): Promise<AccessControlMembersResponseApi> => {
    return apiMutator<AccessControlMembersResponseApi>(
        getOrganizationsProjectsAccessControlMembersRetrieveUrl(organizationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlRoleObjectsRetrieveUrl = (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlRoleObjectsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/access_control_role_objects/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/access_control_role_objects/`
}

/**
 * Object rules configured for one role: the single objects the role's members are granted or denied, regardless of the resource-level rules.
 */
export const organizationsProjectsAccessControlRoleObjectsRetrieve = async (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlRoleObjectsRetrieveParams,
    options?: RequestInit
): Promise<AccessControlObjectRulesResponseApi> => {
    return apiMutator<AccessControlObjectRulesResponseApi>(
        getOrganizationsProjectsAccessControlRoleObjectsRetrieveUrl(organizationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlRolePropertiesRetrieveUrl = (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlRolePropertiesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/access_control_role_properties/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/access_control_role_properties/`
}

/**
 * Property rules configured for one role: the person and event properties the role's members can read, read and write, or not see.
 */
export const organizationsProjectsAccessControlRolePropertiesRetrieve = async (
    organizationId: string,
    id: number,
    params: OrganizationsProjectsAccessControlRolePropertiesRetrieveParams,
    options?: RequestInit
): Promise<AccessControlPropertyRulesResponseApi> => {
    return apiMutator<AccessControlPropertyRulesResponseApi>(
        getOrganizationsProjectsAccessControlRolePropertiesRetrieveUrl(organizationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsAccessControlRolesRetrieveUrl = (
    organizationId: string,
    id: number,
    params?: OrganizationsProjectsAccessControlRolesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/${id}/access_control_roles/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/${id}/access_control_roles/`
}

/**
 * Every role's resolved access to this project and to each resource type in it: the role's own rule, the level that is enforced, and the rule the enforced level comes from. Pass `role_id` for one role.
 */
export const organizationsProjectsAccessControlRolesRetrieve = async (
    organizationId: string,
    id: number,
    params?: OrganizationsProjectsAccessControlRolesRetrieveParams,
    options?: RequestInit
): Promise<AccessControlRolesResponseApi> => {
    return apiMutator<AccessControlRolesResponseApi>(
        getOrganizationsProjectsAccessControlRolesRetrieveUrl(organizationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlDefaultObjectsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/access_control_default_objects/`
}

/**
 * Object rules that apply to everyone without a rule of their own on that object.
 */
export const environmentsAccessControlDefaultObjectsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<AccessControlObjectRulesResponseApi> => {
    return apiMutator<AccessControlObjectRulesResponseApi>(
        getEnvironmentsAccessControlDefaultObjectsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlDefaultPropertiesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/access_control_default_properties/`
}

/**
 * Property rules that apply to everyone without a rule of their own on that property.
 */
export const environmentsAccessControlDefaultPropertiesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<AccessControlPropertyRulesResponseApi> => {
    return apiMutator<AccessControlPropertyRulesResponseApi>(
        getEnvironmentsAccessControlDefaultPropertiesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlDefaultsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/access_control_defaults/`
}

/**
 * The project's default access: the level everyone without a rule of their own gets for the project and for each resource type, plus the resource types that accept rules on single objects.
 */
export const environmentsAccessControlDefaultsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<AccessControlDefaultsResponseApi> => {
    return apiMutator<AccessControlDefaultsResponseApi>(
        getEnvironmentsAccessControlDefaultsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlMemberObjectsRetrieveUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlMemberObjectsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/access_control_member_objects/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/access_control_member_objects/`
}

/**
 * Object rules configured for one member: the dashboards, insights, notebooks and other single objects the member is granted or denied, regardless of the resource-level rules.
 */
export const environmentsAccessControlMemberObjectsRetrieve = async (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlMemberObjectsRetrieveParams,
    options?: RequestInit
): Promise<AccessControlObjectRulesResponseApi> => {
    return apiMutator<AccessControlObjectRulesResponseApi>(
        getEnvironmentsAccessControlMemberObjectsRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlMemberPropertiesRetrieveUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlMemberPropertiesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/access_control_member_properties/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/access_control_member_properties/`
}

/**
 * Property rules configured for one member: the person and event properties the member can read, read and write, or not see.
 */
export const environmentsAccessControlMemberPropertiesRetrieve = async (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlMemberPropertiesRetrieveParams,
    options?: RequestInit
): Promise<AccessControlPropertyRulesResponseApi> => {
    return apiMutator<AccessControlPropertyRulesResponseApi>(
        getEnvironmentsAccessControlMemberPropertiesRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlMembersRetrieveUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsAccessControlMembersRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/access_control_members/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/access_control_members/`
}

/**
 * Every organization member's resolved access to this project and to each resource type in it: the member's own rule, the level that is enforced, and the rule the enforced level comes from (their own, a role's, the project default, or an org-admin bypass). Pass `member_id` for one member.
 */
export const environmentsAccessControlMembersRetrieve = async (
    projectId: string,
    id: number,
    params?: EnvironmentsAccessControlMembersRetrieveParams,
    options?: RequestInit
): Promise<AccessControlMembersResponseApi> => {
    return apiMutator<AccessControlMembersResponseApi>(
        getEnvironmentsAccessControlMembersRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlRoleObjectsRetrieveUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlRoleObjectsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/access_control_role_objects/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/access_control_role_objects/`
}

/**
 * Object rules configured for one role: the single objects the role's members are granted or denied, regardless of the resource-level rules.
 */
export const environmentsAccessControlRoleObjectsRetrieve = async (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlRoleObjectsRetrieveParams,
    options?: RequestInit
): Promise<AccessControlObjectRulesResponseApi> => {
    return apiMutator<AccessControlObjectRulesResponseApi>(
        getEnvironmentsAccessControlRoleObjectsRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlRolePropertiesRetrieveUrl = (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlRolePropertiesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/access_control_role_properties/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/access_control_role_properties/`
}

/**
 * Property rules configured for one role: the person and event properties the role's members can read, read and write, or not see.
 */
export const environmentsAccessControlRolePropertiesRetrieve = async (
    projectId: string,
    id: number,
    params: EnvironmentsAccessControlRolePropertiesRetrieveParams,
    options?: RequestInit
): Promise<AccessControlPropertyRulesResponseApi> => {
    return apiMutator<AccessControlPropertyRulesResponseApi>(
        getEnvironmentsAccessControlRolePropertiesRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsAccessControlRolesRetrieveUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsAccessControlRolesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/environments/${id}/access_control_roles/?${stringifiedParams}`
        : `/api/projects/${projectId}/environments/${id}/access_control_roles/`
}

/**
 * Every role's resolved access to this project and to each resource type in it: the role's own rule, the level that is enforced, and the rule the enforced level comes from. Pass `role_id` for one role.
 */
export const environmentsAccessControlRolesRetrieve = async (
    projectId: string,
    id: number,
    params?: EnvironmentsAccessControlRolesRetrieveParams,
    options?: RequestInit
): Promise<AccessControlRolesResponseApi> => {
    return apiMutator<AccessControlRolesResponseApi>(
        getEnvironmentsAccessControlRolesRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getPropertyAccessControlsRetrieveUrl = (
    projectId: string,
    params: PropertyAccessControlsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/property_access_controls/?${stringifiedParams}`
        : `/api/projects/${projectId}/property_access_controls/`
}

/**
 * Get all property access control rules for a property definition.
 */
export const propertyAccessControlsRetrieve = async (
    projectId: string,
    params: PropertyAccessControlsRetrieveParams,
    options?: RequestInit
): Promise<PropertyAccessControlStateApi> => {
    return apiMutator<PropertyAccessControlStateApi>(getPropertyAccessControlsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPropertyAccessControlsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/property_access_controls/`
}

/**
 * Create or update a property access control rule.
 */
export const propertyAccessControlsCreate = async (
    projectId: string,
    propertyAccessControlUpdateApi: PropertyAccessControlUpdateApi,
    options?: RequestInit
): Promise<PropertyAccessControlRuleApi> => {
    return apiMutator<PropertyAccessControlRuleApi>(getPropertyAccessControlsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(propertyAccessControlUpdateApi),
    })
}

export const getPropertyAccessControlsDestroyUrl = (projectId: string, params: PropertyAccessControlsDestroyParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/property_access_controls/?${stringifiedParams}`
        : `/api/projects/${projectId}/property_access_controls/`
}

/**
 * Delete a property access control rule. The rule is identified by `property_definition_id` plus an optional `organization_member` or `role` query parameter. Omitting both targets deletes the default rule.
 */
export const propertyAccessControlsDestroy = async (
    projectId: string,
    params: PropertyAccessControlsDestroyParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPropertyAccessControlsDestroyUrl(projectId, params), {
        ...options,
        method: 'DELETE',
    })
}
