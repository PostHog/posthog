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
    DeploymentProjectApi,
    DeploymentProjectsDeploymentsEventsListParams,
    DeploymentProjectsDeploymentsListParams,
    DeploymentProjectsListParams,
    PaginatedDeploymentEventListApi,
    PaginatedDeploymentListApi,
    PaginatedDeploymentProjectListApi,
    PatchedDeploymentProjectApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

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
    deploymentProjectApi: NonReadonly<DeploymentProjectApi>,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(deploymentProjectApi),
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
): Promise<DeploymentActionResponseApi> => {
    return apiMutator<DeploymentActionResponseApi>(
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
    deploymentProjectApi: NonReadonly<DeploymentProjectApi>,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(deploymentProjectApi),
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
    patchedDeploymentProjectApi?: NonReadonly<PatchedDeploymentProjectApi>,
    options?: RequestInit
): Promise<DeploymentProjectApi> => {
    return apiMutator<DeploymentProjectApi>(getDeploymentProjectsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDeploymentProjectApi),
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
