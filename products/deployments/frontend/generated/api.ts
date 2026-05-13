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
import type { DeploymentApi, DeploymentsListParams, PaginatedDeploymentListApi } from './api.schemas'

export const getDeploymentsListUrl = (projectId: string, params?: DeploymentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/deployments/?${stringifiedParams}`
        : `/api/projects/${projectId}/deployments/`
}

/**
 * Read-only viewset for the Deployments product.

`list` and `retrieve` are wired against the model queryset. The
`@action` stubs (`redeploy`, `rollback`, `refresh_preview`) intentionally
return 501 — they exist so OpenAPI / MCP can discover the surface area
while behavior lands in follow-up commits.
 */
export const deploymentsList = async (
    projectId: string,
    params?: DeploymentsListParams,
    options?: RequestInit
): Promise<PaginatedDeploymentListApi> => {
    return apiMutator<PaginatedDeploymentListApi>(getDeploymentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDeploymentsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployments/${id}/`
}

/**
 * Read-only viewset for the Deployments product.

`list` and `retrieve` are wired against the model queryset. The
`@action` stubs (`redeploy`, `rollback`, `refresh_preview`) intentionally
return 501 — they exist so OpenAPI / MCP can discover the surface area
while behavior lands in follow-up commits.
 */
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

export const getDeploymentsRedeployCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployments/${id}/redeploy/`
}

/**
 * Read-only viewset for the Deployments product.

`list` and `retrieve` are wired against the model queryset. The
`@action` stubs (`redeploy`, `rollback`, `refresh_preview`) intentionally
return 501 — they exist so OpenAPI / MCP can discover the surface area
while behavior lands in follow-up commits.
 */
export const deploymentsRedeployCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getDeploymentsRedeployCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getDeploymentsRefreshPreviewCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployments/${id}/refresh-preview/`
}

/**
 * Read-only viewset for the Deployments product.

`list` and `retrieve` are wired against the model queryset. The
`@action` stubs (`redeploy`, `rollback`, `refresh_preview`) intentionally
return 501 — they exist so OpenAPI / MCP can discover the surface area
while behavior lands in follow-up commits.
 */
export const deploymentsRefreshPreviewCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getDeploymentsRefreshPreviewCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getDeploymentsRollbackCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployments/${id}/rollback/`
}

/**
 * Read-only viewset for the Deployments product.

`list` and `retrieve` are wired against the model queryset. The
`@action` stubs (`redeploy`, `rollback`, `refresh_preview`) intentionally
return 501 — they exist so OpenAPI / MCP can discover the surface area
while behavior lands in follow-up commits.
 */
export const deploymentsRollbackCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getDeploymentsRollbackCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}
