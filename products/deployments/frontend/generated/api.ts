/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 *
 * NOTE: This is a placeholder shipped with the Deployments scaffold so the
 * TypeScript build passes before `hogli build:openapi` has been run. The
 * next run of `hogli build:openapi` will overwrite this file with the real
 * generated client.
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type { DeploymentApi, PaginatedDeploymentListApi } from './api.schemas'

export const getDeploymentsListUrl = (projectId: string): string => {
    return `/api/projects/${projectId}/deployments/`
}

export const deploymentsList = async (
    projectId: string,
    options?: RequestInit
): Promise<PaginatedDeploymentListApi> => {
    return apiMutator<PaginatedDeploymentListApi>(getDeploymentsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDeploymentsRetrieveUrl = (projectId: string, id: string): string => {
    return `/api/projects/${projectId}/deployments/${id}/`
}

export const deploymentsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentApi> => {
    return apiMutator<DeploymentApi>(getDeploymentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
