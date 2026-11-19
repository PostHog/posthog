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
    CreateDashboardV2InputApi,
    DashboardV2DetailApi,
    DashboardsV2ListParams,
    PaginatedDashboardV2SummaryListApi,
    UpdateDashboardV2InputApi,
} from './api.schemas'

export const getDashboardsV2ListUrl = (projectId: string, params?: DashboardsV2ListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards_v2/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards_v2/`
}

/**
 * List the dashboards of the project, the most recently saved first. Rows do not include the spec.
 */
export const dashboardsV2List = async (
    projectId: string,
    params?: DashboardsV2ListParams,
    options?: RequestInit
): Promise<PaginatedDashboardV2SummaryListApi> => {
    return apiMutator<PaginatedDashboardV2SummaryListApi>(getDashboardsV2ListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsV2CreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboards_v2/`
}

/**
 * Create a dashboard from a spec. The dashboard starts at version 1.
 */
export const dashboardsV2Create = async (
    projectId: string,
    createDashboardV2InputApi: CreateDashboardV2InputApi,
    options?: RequestInit
): Promise<DashboardV2DetailApi> => {
    return apiMutator<DashboardV2DetailApi>(getDashboardsV2CreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createDashboardV2InputApi),
    })
}

export const getDashboardsV2RetrieveUrl = (projectId: string, uid: string) => {
    return `/api/projects/${projectId}/dashboards_v2/${uid}/`
}

/**
 * Get a dashboard with its spec.
 */
export const dashboardsV2Retrieve = async (
    projectId: string,
    uid: string,
    options?: RequestInit
): Promise<DashboardV2DetailApi> => {
    return apiMutator<DashboardV2DetailApi>(getDashboardsV2RetrieveUrl(projectId, uid), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsV2UpdateUrl = (projectId: string, uid: string) => {
    return `/api/projects/${projectId}/dashboards_v2/${uid}/`
}

/**
 * Save a spec as the next version of a dashboard. The uid of a dashboard cannot change.
 */
export const dashboardsV2Update = async (
    projectId: string,
    uid: string,
    updateDashboardV2InputApi: UpdateDashboardV2InputApi,
    options?: RequestInit
): Promise<DashboardV2DetailApi> => {
    return apiMutator<DashboardV2DetailApi>(getDashboardsV2UpdateUrl(projectId, uid), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(updateDashboardV2InputApi),
    })
}

export const getDashboardsV2DestroyUrl = (projectId: string, uid: string) => {
    return `/api/projects/${projectId}/dashboards_v2/${uid}/`
}

/**
 * Delete a dashboard. Its uid can then be used for a new dashboard.
 */
export const dashboardsV2Destroy = async (projectId: string, uid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDashboardsV2DestroyUrl(projectId, uid), {
        ...options,
        method: 'DELETE',
    })
}
