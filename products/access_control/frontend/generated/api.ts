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
    PropertyAccessControlRuleApi,
    PropertyAccessControlStateApi,
    PropertyAccessControlUpdateApi,
    PropertyAccessControlsDestroyParams,
    PropertyAccessControlsRetrieveParams,
} from './api.schemas'

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
