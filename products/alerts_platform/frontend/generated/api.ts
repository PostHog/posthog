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
    AlertReceiverApi,
    AlertReceiverWriteApi,
    AlertRouteApi,
    AlertRouteWriteApi,
    PaginatedPlatformAlertConfigurationListApi,
    PatchedAlertReceiverWriteApi,
    PatchedAlertRouteWriteApi,
    PatchedPlatformAlertConfigurationEditApi,
    PlatformAlertApi,
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationCreateApi,
    PlatformAlertConfigurationEditApi,
    PlatformAlertCreateDestinationApi,
    PlatformAlertDeleteDestinationApi,
    PlatformAlertDestinationApi,
    PlatformAlertEventApi,
    PlatformAlertGroupSnoozeApi,
    PlatformAlertSnoozeApi,
    PlatformAlertsEventsListParams,
    PlatformAlertsListParams,
} from './api.schemas'

export const getPlatformAlertReceiversListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/platform_alert_receivers/`
}

/**
 * List the project's alert receivers.
 */
export const platformAlertReceiversList = async (
    projectId: string,
    options?: RequestInit
): Promise<AlertReceiverApi[]> => {
    return apiMutator<AlertReceiverApi[]>(getPlatformAlertReceiversListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getPlatformAlertReceiversCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/platform_alert_receivers/`
}

/**
 * Add a receiver that routes can send alerts to.
 */
export const platformAlertReceiversCreate = async (
    projectId: string,
    alertReceiverWriteApi: AlertReceiverWriteApi,
    options?: RequestInit
): Promise<AlertReceiverApi> => {
    return apiMutator<AlertReceiverApi>(getPlatformAlertReceiversCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(alertReceiverWriteApi),
    })
}

export const getPlatformAlertReceiversPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alert_receivers/${id}/`
}

/**
 * Change a receiver. Destination fields replace the stored destination and need the type.
 */
export const platformAlertReceiversPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAlertReceiverWriteApi?: PatchedAlertReceiverWriteApi,
    options?: RequestInit
): Promise<AlertReceiverApi> => {
    return apiMutator<AlertReceiverApi>(getPlatformAlertReceiversPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAlertReceiverWriteApi),
    })
}

export const getPlatformAlertReceiversDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alert_receivers/${id}/`
}

/**
 * Delete a receiver and every route that sends to it.
 */
export const platformAlertReceiversDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPlatformAlertReceiversDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getPlatformAlertRoutesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/platform_alert_routes/`
}

/**
 * List the project's alert routes, in the order delivery reads them.
 */
export const platformAlertRoutesList = async (projectId: string, options?: RequestInit): Promise<AlertRouteApi[]> => {
    return apiMutator<AlertRouteApi[]>(getPlatformAlertRoutesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getPlatformAlertRoutesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/platform_alert_routes/`
}

/**
 * Add a route. Every alert whose labels match it also sends to its receiver.
 */
export const platformAlertRoutesCreate = async (
    projectId: string,
    alertRouteWriteApi: AlertRouteWriteApi,
    options?: RequestInit
): Promise<AlertRouteApi> => {
    return apiMutator<AlertRouteApi>(getPlatformAlertRoutesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(alertRouteWriteApi),
    })
}

export const getPlatformAlertRoutesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alert_routes/${id}/`
}

/**
 * Change a route. Fields left out keep their stored value.
 */
export const platformAlertRoutesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAlertRouteWriteApi?: PatchedAlertRouteWriteApi,
    options?: RequestInit
): Promise<AlertRouteApi> => {
    return apiMutator<AlertRouteApi>(getPlatformAlertRoutesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAlertRouteWriteApi),
    })
}

export const getPlatformAlertRoutesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alert_routes/${id}/`
}

/**
 * Delete a route.
 */
export const platformAlertRoutesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPlatformAlertRoutesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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

export const getPlatformAlertsEventsListUrl = (
    projectId: string,
    id: string,
    params?: PlatformAlertsEventsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/platform_alerts/${id}/events/?${stringifiedParams}`
        : `/api/projects/${projectId}/platform_alerts/${id}/events/`
}

/**
 * The alert's history over the past 30 days, newest first: checks that moved its state or failed, and the changes people made to it. Checks that changed nothing are left out.
 * @summary List an alert's history
 */
export const platformAlertsEventsList = async (
    projectId: string,
    id: string,
    params?: PlatformAlertsEventsListParams,
    options?: RequestInit
): Promise<PlatformAlertEventApi[]> => {
    return apiMutator<PlatformAlertEventApi[]>(getPlatformAlertsEventsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getPlatformAlertsResetCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/reset/`
}

/**
 * Clears a broken alert's failure count so it is checked again.
 * @summary Reset a broken alert
 */
export const platformAlertsResetCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PlatformAlertConfigurationApi> => {
    return apiMutator<PlatformAlertConfigurationApi>(getPlatformAlertsResetCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getPlatformAlertsSnoozeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/platform_alerts/${id}/snooze/`
}

/**
 * @summary Snooze a whole alert
 */
export const platformAlertsSnoozeCreate = async (
    projectId: string,
    id: string,
    platformAlertSnoozeApi: PlatformAlertSnoozeApi,
    options?: RequestInit
): Promise<PlatformAlertConfigurationApi> => {
    return apiMutator<PlatformAlertConfigurationApi>(getPlatformAlertsSnoozeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(platformAlertSnoozeApi),
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
