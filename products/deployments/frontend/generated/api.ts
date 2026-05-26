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
    DeploymentActionResponseApi,
    DeploymentApi,
    DeploymentCreateInputApi,
    DeploymentLogsResponseApi,
    DeploymentProjectApi,
    DeploymentProjectCreateApi,
    DeploymentProjectRefreshResponseApi,
    DeploymentProjectWriteApi,
    DeploymentProjectsDeploymentsEventsListParams,
    DeploymentProjectsDeploymentsListParams,
    DeploymentProjectsListParams,
    DetectConfigRequestApi,
    DetectConfigResponseApi,
    PaginatedDeploymentEventListApi,
    PaginatedDeploymentListApi,
    PaginatedDeploymentProjectListApi,
    PatchedDeploymentProjectWriteApi,
} from './api.schemas'

export const getDeploymentProjectsListUrl = (projectId: string, params?: DeploymentProjectsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/deployment_projects/?${stringifiedParams}`
        : `/api/projects/${projectId}/deployment_projects/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsList = async (
    projectId: string,
    params?: DeploymentProjectsListParams,
    options?: RequestInit
): Promise<PaginatedDeploymentProjectListApi> => {
    return apiMutator<PaginatedDeploymentProjectListApi>(getDeploymentProjectsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDeploymentProjectsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/deployment_projects/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsCreate = async (
    projectId: string,
    deploymentProjectCreateApi: DeploymentProjectCreateApi,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(deploymentProjectCreateApi),
    })
}

export const getDeploymentProjectsDeploymentsListUrl = (
    projectId: string,
    deploymentProjectId: string,
    params?: DeploymentProjectsDeploymentsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/?${stringifiedParams}`
        : `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsList = async (
    projectId: string,
    deploymentProjectId: string,
    params?: DeploymentProjectsDeploymentsListParams,
    options?: RequestInit
): Promise<PaginatedDeploymentListApi> => {
    return apiMutator<PaginatedDeploymentListApi>(
        getDeploymentProjectsDeploymentsListUrl(projectId, deploymentProjectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDeploymentProjectsDeploymentsCreateUrl = (projectId: string, deploymentProjectId: string) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsCreate = async (
    projectId: string,
    deploymentProjectId: string,
    deploymentCreateInputApi?: DeploymentCreateInputApi,
    options?: RequestInit
): Promise<DeploymentApi> => {
    return apiMutator<DeploymentApi>(getDeploymentProjectsDeploymentsCreateUrl(projectId, deploymentProjectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(deploymentCreateInputApi),
    })
}

export const getDeploymentProjectsDeploymentsRetrieveUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string
) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsRetrieve = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentApi> => {
    return apiMutator<DeploymentApi>(getDeploymentProjectsDeploymentsRetrieveUrl(projectId, deploymentProjectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDeploymentProjectsDeploymentsCancelCreateUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string
) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/cancel/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsCancelCreate = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentActionResponseApi> => {
    return apiMutator<DeploymentActionResponseApi>(
        getDeploymentProjectsDeploymentsCancelCreateUrl(projectId, deploymentProjectId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getDeploymentProjectsDeploymentsEventsListUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    params?: DeploymentProjectsDeploymentsEventsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/events/?${stringifiedParams}`
        : `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/events/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsEventsList = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    params?: DeploymentProjectsDeploymentsEventsListParams,
    options?: RequestInit
): Promise<PaginatedDeploymentEventListApi> => {
    return apiMutator<PaginatedDeploymentEventListApi>(
        getDeploymentProjectsDeploymentsEventsListUrl(projectId, deploymentProjectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDeploymentProjectsDeploymentsLogsRetrieveUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string
) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/logs/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsLogsRetrieve = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentLogsResponseApi> => {
    return apiMutator<DeploymentLogsResponseApi>(
        getDeploymentProjectsDeploymentsLogsRetrieveUrl(projectId, deploymentProjectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDeploymentProjectsDeploymentsRedeployCreateUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string
) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/redeploy/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsRedeployCreate = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentApi> => {
    return apiMutator<DeploymentApi>(
        getDeploymentProjectsDeploymentsRedeployCreateUrl(projectId, deploymentProjectId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getDeploymentProjectsDeploymentsRefreshPreviewCreateUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string
) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/refresh_preview/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsRefreshPreviewCreate = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentApi> => {
    return apiMutator<DeploymentApi>(
        getDeploymentProjectsDeploymentsRefreshPreviewCreateUrl(projectId, deploymentProjectId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getDeploymentProjectsDeploymentsRollbackCreateUrl = (
    projectId: string,
    deploymentProjectId: string,
    id: string
) => {
    return `/api/projects/${projectId}/deployment_projects/${deploymentProjectId}/deployments/${id}/rollback/`
}

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const deploymentProjectsDeploymentsRollbackCreate = async (
    projectId: string,
    deploymentProjectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentApi> => {
    return apiMutator<DeploymentApi>(
        getDeploymentProjectsDeploymentsRollbackCreateUrl(projectId, deploymentProjectId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getDeploymentProjectsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployment_projects/${id}/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDeploymentProjectsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployment_projects/${id}/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsUpdate = async (
    projectId: string,
    id: string,
    deploymentProjectWriteApi: DeploymentProjectWriteApi,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(deploymentProjectWriteApi),
    })
}

export const getDeploymentProjectsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployment_projects/${id}/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDeploymentProjectWriteApi?: PatchedDeploymentProjectWriteApi,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDeploymentProjectWriteApi),
    })
}

export const getDeploymentProjectsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployment_projects/${id}/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const deploymentProjectsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDeploymentProjectsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDeploymentProjectsRefreshCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/deployment_projects/${id}/refresh/`
}

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 * @summary Refresh a deployment project's GitHub branch
 */
export const deploymentProjectsRefreshCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DeploymentProjectRefreshResponseApi> => {
    return apiMutator<DeploymentProjectRefreshResponseApi>(getDeploymentProjectsRefreshCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getDeploymentProjectsDetectCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/deployment_projects/detect/`
}

/**
 * Pure inspection — no git access, no DB writes. The connect-repo UI calls this after fetching `package.json` (via the team's GitHub integration) and uses the response to prefill the form.
 * @summary Suggest project config from a repo's package.json and lockfiles
 */
export const deploymentProjectsDetectCreate = async (
    projectId: string,
    detectConfigRequestApi?: DetectConfigRequestApi,
    options?: RequestInit
): Promise<DetectConfigResponseApi> => {
    return apiMutator<DetectConfigResponseApi>(getDeploymentProjectsDetectCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(detectConfigRequestApi),
    })
}
