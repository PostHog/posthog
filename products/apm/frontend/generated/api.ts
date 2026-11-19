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
    ApmDependenciesListParams,
    ApmDeploymentsListParams,
    ApmEndpointTimeSpentListParams,
    ApmEndpointsListParams,
    ApmServiceMapListParams,
    ApmServicesListParams,
    ApmUsageListParams,
    DependenciesResponseApi,
    DeploymentsResponseApi,
    EndpointTimeSpentResponseApi,
    EndpointsHealthResponseApi,
    ServiceMapResponseApi,
    ServiceUsageResponseApi,
    ServicesHealthResponseApi,
} from './api.schemas'

export const getApmDependenciesListUrl = (projectId: string, params?: ApmDependenciesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/dependencies/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/dependencies/`
}

/**
 * Caller to callee edges over the whole window, including inferred dependencies. Same gate and window as services.
 */
export const apmDependenciesList = async (
    projectId: string,
    params?: ApmDependenciesListParams,
    options?: RequestInit
): Promise<DependenciesResponseApi> => {
    return apiMutator<DependenciesResponseApi>(getApmDependenciesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApmDeploymentsListUrl = (projectId: string, params: ApmDeploymentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/deployments/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/deployments/`
}

/**
 * One service's versions in an environment and window, each compared with the one before. Same gate and window as services.
 */
export const apmDeploymentsList = async (
    projectId: string,
    params: ApmDeploymentsListParams,
    options?: RequestInit
): Promise<DeploymentsResponseApi> => {
    return apiMutator<DeploymentsResponseApi>(getApmDeploymentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApmEndpointTimeSpentListUrl = (projectId: string, params: ApmEndpointTimeSpentListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/endpoint_time_spent/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/endpoint_time_spent/`
}

/**
 * Where one endpoint's request time goes, by service and inferred dependency. Same gate and window as services.
 */
export const apmEndpointTimeSpentList = async (
    projectId: string,
    params: ApmEndpointTimeSpentListParams,
    options?: RequestInit
): Promise<EndpointTimeSpentResponseApi> => {
    return apiMutator<EndpointTimeSpentResponseApi>(getApmEndpointTimeSpentListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApmEndpointsListUrl = (projectId: string, params?: ApmEndpointsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/endpoints/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/endpoints/`
}

/**
 * One health row per service and entry span name, worst first. Same gate and window as services.
 */
export const apmEndpointsList = async (
    projectId: string,
    params?: ApmEndpointsListParams,
    options?: RequestInit
): Promise<EndpointsHealthResponseApi> => {
    return apiMutator<EndpointsHealthResponseApi>(getApmEndpointsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApmServiceMapListUrl = (projectId: string, params?: ApmServiceMapListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/service_map/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/service_map/`
}

/**
 * Service-to-service call edges in an environment and window. Same gate and window as services.
 */
export const apmServiceMapList = async (
    projectId: string,
    params?: ApmServiceMapListParams,
    options?: RequestInit
): Promise<ServiceMapResponseApi> => {
    return apiMutator<ServiceMapResponseApi>(getApmServiceMapListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApmServicesListUrl = (projectId: string, params?: ApmServicesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/services/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/services/`
}

/**
 * One health row per service in an environment and window, worst first.
 *
 * Read-only, and dark for every team without the product flag: the flag gates the scene, the
 * nav entry, and this endpoint together.
 */
export const apmServicesList = async (
    projectId: string,
    params?: ApmServicesListParams,
    options?: RequestInit
): Promise<ServicesHealthResponseApi> => {
    return apiMutator<ServicesHealthResponseApi>(getApmServicesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getApmUsageListUrl = (projectId: string, params?: ApmUsageListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/apm/usage/?${stringifiedParams}`
        : `/api/projects/${projectId}/apm/usage/`
}

/**
 * How much each service sends across logs, traces, and metrics in a window. Same gate and window as services.
 *
 * Usage covers every environment: logs and metrics often carry no environment attribute, so a
 * filter would hide the services that send the most.
 */
export const apmUsageList = async (
    projectId: string,
    params?: ApmUsageListParams,
    options?: RequestInit
): Promise<ServiceUsageResponseApi> => {
    return apiMutator<ServiceUsageResponseApi>(getApmUsageListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
