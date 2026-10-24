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
import type { ApmServicesListParams, ServicesHealthResponseApi } from './api.schemas'

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
): Promise<ServicesHealthResponseApi[]> => {
    return apiMutator<ServicesHealthResponseApi[]>(getApmServicesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
