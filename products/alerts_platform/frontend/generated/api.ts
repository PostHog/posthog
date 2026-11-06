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
    PatchedPlatformAlertConfigurationEditApi,
    PlatformAlertApi,
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationCreateApi,
    PlatformAlertConfigurationEditApi,
    PlatformAlertCreateDestinationApi,
    PlatformAlertDeleteDestinationApi,
    PlatformAlertDestinationApi,
    PlatformAlertGroupSnoozeApi,
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

export const getPlatformAlertsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/platform_alerts/`
}

export const platformAlertsCreate = async (
    projectId: string,
    platformAlertConfigurationCreateApi?: PlatformAlertConfigurationCreateApi,
    options?: RequestInit
): Promise<PlatformAlertConfigurationApi> => {
    return apiMutator<PlatformAlertConfigurationApi>(getPlatformAlertsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(platformAlertConfigurationCreateApi),
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

export const getPlatformAlertsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/`
}

export const platformAlertsUpdate = async (
    projectId: string,
    id: string,
    platformAlertConfigurationEditApi?: PlatformAlertConfigurationEditApi,
    options?: RequestInit
): Promise<PlatformAlertConfigurationApi> => {
    return apiMutator<PlatformAlertConfigurationApi>(getPlatformAlertsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(platformAlertConfigurationEditApi),
    })
}

export const getPlatformAlertsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/`
}

export const platformAlertsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedPlatformAlertConfigurationEditApi?: PatchedPlatformAlertConfigurationEditApi,
    options?: RequestInit
): Promise<PlatformAlertConfigurationApi> => {
    return apiMutator<PlatformAlertConfigurationApi>(getPlatformAlertsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPlatformAlertConfigurationEditApi),
    })
}

export const getPlatformAlertsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/`
}

export const platformAlertsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getPlatformAlertsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getPlatformAlertsDestinationsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/destinations/`
}

/**
 * List the notification destinations of an alert.
 */
export const platformAlertsDestinationsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PlatformAlertDestinationApi[]> => {
    return apiMutator<PlatformAlertDestinationApi[]>(getPlatformAlertsDestinationsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPlatformAlertsDestinationsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/destinations/`
}

/**
 * Add a notification destination to an alert. It hears the transitions in `event_kinds`. A PagerDuty destination opens an incident when the alert fires and resolves it when the alert resolves.
 */
export const platformAlertsDestinationsCreate = async (
    projectId: string,
    id: string,
    platformAlertCreateDestinationApi: PlatformAlertCreateDestinationApi,
    options?: RequestInit
): Promise<PlatformAlertDestinationApi> => {
    return apiMutator<PlatformAlertDestinationApi>(getPlatformAlertsDestinationsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(platformAlertCreateDestinationApi),
    })
}

export const getPlatformAlertsDestinationsDeleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/destinations/delete/`
}

/**
 * Delete notification destinations of an alert.
 */
export const platformAlertsDestinationsDeleteCreate = async (
    projectId: string,
    id: string,
    platformAlertDeleteDestinationApi: PlatformAlertDeleteDestinationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPlatformAlertsDestinationsDeleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(platformAlertDeleteDestinationApi),
    })
}

export const getPlatformAlertsSnoozeGroupCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/snooze_group/`
}

/**
 * @summary Snooze one group of a grouped alert
 */
export const platformAlertsSnoozeGroupCreate = async (
    projectId: string,
    id: string,
    platformAlertGroupSnoozeApi: PlatformAlertGroupSnoozeApi,
    options?: RequestInit
): Promise<PlatformAlertApi> => {
    return apiMutator<PlatformAlertApi>(getPlatformAlertsSnoozeGroupCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(platformAlertGroupSnoozeApi),
    })
}
