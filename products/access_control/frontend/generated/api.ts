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
    AccessControlMemberRuleRequestApi,
    AccessControlMembersResponseApi,
    AccessControlObjectRulesResponseApi,
    AccessControlPropertyRulesResponseApi,
    AccessControlRoleRuleRequestApi,
    AccessControlRolesResponseApi,
    AccessControlRuleRequestApi,
    AccessControlStoredRuleApi,
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
 * Object rules that apply to everyone in the project without a rule of their own on that object.
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
 * Property rules that apply to everyone in the project without a rule of their own on that property.
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

export const getOrganizationsProjectsAccessControlDefaultRulesUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_default_rules/`
}

/**
 * Set or clear the rule everyone in the project gets for a scope, unless a member or role rule of their own applies. The scope is the project (`resource: project` with the project id as `resource_id`), a whole resource type, one object, or one property definition. A null `access_level` removes the rule. Returns the stored rule with 201 when created and 200 when updated, and 204 with no body when the rule is cleared.
 */
export const organizationsProjectsAccessControlDefaultRulesUpdate = async (
    organizationId: string,
    id: number,
    accessControlRuleRequestApi: AccessControlRuleRequestApi,
    options?: RequestInit
): Promise<AccessControlStoredRuleApi | void> => {
    return apiMutator<AccessControlStoredRuleApi | void>(
        getOrganizationsProjectsAccessControlDefaultRulesUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(accessControlRuleRequestApi),
        }
    )
}

export const getOrganizationsProjectsAccessControlDefaultsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_defaults/`
}

/**
 * The project's default access. Returns the level that applies to the project and to each resource type when a member or a role has no rule of their own. Also lists the resource types that accept rules on single objects, with the levels such a rule can set.
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
 * Object rules configured for a member: the single objects, for example a dashboard or a notebook, the member is granted or denied, regardless of the resource-level rules.
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
 * Property rules configured for a member: the person and event properties the member can read, read and write, or not see.
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

export const getOrganizationsProjectsAccessControlMemberRulesUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_member_rules/`
}

/**
 * Set or clear one member's rule for a scope. A member rule applies to that person only and takes precedence over their role rules and the default. The scope is the project (`resource: project` with the project id as `resource_id`), a whole resource type, one object, or one property definition. A null `access_level` removes the rule. Returns the stored rule with 201 when created and 200 when updated, and 204 with no body when the rule is cleared.
 */
export const organizationsProjectsAccessControlMemberRulesUpdate = async (
    organizationId: string,
    id: number,
    accessControlMemberRuleRequestApi: AccessControlMemberRuleRequestApi,
    options?: RequestInit
): Promise<AccessControlStoredRuleApi | void> => {
    return apiMutator<AccessControlStoredRuleApi | void>(
        getOrganizationsProjectsAccessControlMemberRulesUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(accessControlMemberRuleRequestApi),
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
 * Every organization member's access in this project. For the project and for each resource type, the response gives the member's own rule and the level that is enforced. It also says where the enforced level comes from: the member's rule, a role's rule, the project default, or full access as an organization admin. Pass `member_id` for one member.
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
 * Object rules configured for a role: the single objects the role's members are granted or denied, regardless of the resource-level rules.
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
 * Property rules configured for a role: the person and event properties the role's members can read, read and write, or not see.
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

export const getOrganizationsProjectsAccessControlRoleRulesUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/access_control_role_rules/`
}

/**
 * Set or clear one role's rule for a scope. A role rule applies to every member of the role and takes precedence over the default. Requires the role-based access feature. The scope is the project (`resource: project` with the project id as `resource_id`), a whole resource type, one object, or one property definition. A null `access_level` removes the rule. Returns the stored rule with 201 when created and 200 when updated, and 204 with no body when the rule is cleared.
 */
export const organizationsProjectsAccessControlRoleRulesUpdate = async (
    organizationId: string,
    id: number,
    accessControlRoleRuleRequestApi: AccessControlRoleRuleRequestApi,
    options?: RequestInit
): Promise<AccessControlStoredRuleApi | void> => {
    return apiMutator<AccessControlStoredRuleApi | void>(
        getOrganizationsProjectsAccessControlRoleRulesUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(accessControlRoleRuleRequestApi),
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
