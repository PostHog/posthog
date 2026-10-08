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
    PaginatedPlatformAlertConfigurationListApi,
    PlatformAlertConfigurationApi,
    PlatformAlertsListParams,
} from './api.schemas'

export const getPlatformAlertsListUrl = (projectId: string, params?: PlatformAlertsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/platform_alerts/?${stringifiedParams}`
        : `/api/projects/${projectId}/platform_alerts/`
}

export const platformAlertsList = async (
    projectId: string,
    params?: PlatformAlertsListParams,
    options?: RequestInit
): Promise<PaginatedPlatformAlertConfigurationListApi> => {
    return apiMutator<PaginatedPlatformAlertConfigurationListApi>(getPlatformAlertsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPlatformAlertsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/`
}

export const platformAlertsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PlatformAlertConfigurationApi> => {
    return apiMutator<PlatformAlertConfigurationApi>(getPlatformAlertsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
