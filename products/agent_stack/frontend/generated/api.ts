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
    AgentApplicationApi,
    AgentApplicationRevisionApi,
    AgentApplicationsListParams,
    AgentApplicationsRevisionsListParams,
    AgentApplicationsSessionsCancel200,
    AgentApplicationsSessionsList200,
    AgentApplicationsSessionsLogs200,
    AgentApplicationsSessionsRetrieve200,
    CompleteUploadRequestApi,
    DisableRevisionRequestApi,
    PaginatedAgentApplicationListApi,
    PaginatedAgentApplicationRevisionListApi,
    PatchedAgentApplicationApi,
    PreviewRevisionRequestApi,
    PromoteRevisionRequestApi,
    StartDeployRequestApi,
    StartDeployResponseApi,
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

export const getAgentApplicationsListUrl = (projectId: string, params?: AgentApplicationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/`
}

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsList = async (
    projectId: string,
    params?: AgentApplicationsListParams,
    options?: RequestInit
): Promise<PaginatedAgentApplicationListApi> => {
    return apiMutator<PaginatedAgentApplicationListApi>(getAgentApplicationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_applications/`
}

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsCreate = async (
    projectId: string,
    agentApplicationApi: NonReadonly<AgentApplicationApi>,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agentApplicationApi),
    })
}

export const getAgentApplicationsRevisionsListUrl = (
    projectId: string,
    applicationId: string,
    params?: AgentApplicationsRevisionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/`
}

/**
 * Revisions for an application — read-only, nested under agent_applications.
 */
export const agentApplicationsRevisionsList = async (
    projectId: string,
    applicationId: string,
    params?: AgentApplicationsRevisionsListParams,
    options?: RequestInit
): Promise<PaginatedAgentApplicationRevisionListApi> => {
    return apiMutator<PaginatedAgentApplicationRevisionListApi>(
        getAgentApplicationsRevisionsListUrl(projectId, applicationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRevisionsRetrieveUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/`
}

/**
 * Revisions for an application — read-only, nested under agent_applications.
 */
export const agentApplicationsRevisionsRetrieve = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentApplicationRevisionApi> => {
    return apiMutator<AgentApplicationRevisionApi>(
        getAgentApplicationsRevisionsRetrieveUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsSessionsListUrl = (projectId: string, applicationId: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/sessions/`
}

/**
 * List sessions for an agent application (proxied from agent-janitor).
 */
export const agentApplicationsSessionsList = async (
    projectId: string,
    applicationId: string,
    options?: RequestInit
): Promise<AgentApplicationsSessionsList200> => {
    return apiMutator<AgentApplicationsSessionsList200>(getAgentApplicationsSessionsListUrl(projectId, applicationId), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsSessionsRetrieveUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/sessions/${id}/`
}

/**
 * Fetch a single session by id (proxied from agent-janitor).
 */
export const agentApplicationsSessionsRetrieve = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentApplicationsSessionsRetrieve200> => {
    return apiMutator<AgentApplicationsSessionsRetrieve200>(
        getAgentApplicationsSessionsRetrieveUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsSessionsCancelUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/sessions/${id}/cancel/`
}

/**
 * Cancel a running session (proxied from agent-janitor).
 */
export const agentApplicationsSessionsCancel = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentApplicationsSessionsCancel200> => {
    return apiMutator<AgentApplicationsSessionsCancel200>(
        getAgentApplicationsSessionsCancelUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getAgentApplicationsSessionsLogsUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/sessions/${id}/logs/`
}

/**
 * Read per-session log entries from ClickHouse.
 */
export const agentApplicationsSessionsLogs = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentApplicationsSessionsLogs200> => {
    return apiMutator<AgentApplicationsSessionsLogs200>(
        getAgentApplicationsSessionsLogsUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/`
}

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/`
}

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsUpdate = async (
    projectId: string,
    id: string,
    agentApplicationApi: NonReadonly<AgentApplicationApi>,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agentApplicationApi),
    })
}

export const getAgentApplicationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/`
}

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAgentApplicationApi?: NonReadonly<PatchedAgentApplicationApi>,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAgentApplicationApi),
    })
}

export const getAgentApplicationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/`
}

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsCompleteUploadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/complete_upload/`
}

/**
 * v1: transitions the revision straight to state=ready.
 */
export const agentApplicationsCompleteUploadCreate = async (
    projectId: string,
    id: string,
    completeUploadRequestApi: CompleteUploadRequestApi,
    options?: RequestInit
): Promise<AgentApplicationRevisionApi> => {
    return apiMutator<AgentApplicationRevisionApi>(getAgentApplicationsCompleteUploadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(completeUploadRequestApi),
    })
}

export const getAgentApplicationsDisableRevisionCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/disable_revision/`
}

/**
 * Set a revision's deployment_status to disabled. Pulls it out of any traffic role.
 */
export const agentApplicationsDisableRevisionCreate = async (
    projectId: string,
    id: string,
    disableRevisionRequestApi: DisableRevisionRequestApi,
    options?: RequestInit
): Promise<AgentApplicationRevisionApi> => {
    return apiMutator<AgentApplicationRevisionApi>(getAgentApplicationsDisableRevisionCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(disableRevisionRequestApi),
    })
}

export const getAgentApplicationsEnvUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/env/`
}

/**
 * PUT: replace the entire env. PATCH: merge individual keys (set to null to remove).
 */
export const agentApplicationsEnvUpdate = async (
    projectId: string,
    id: string,
    agentApplicationApi: NonReadonly<AgentApplicationApi>,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsEnvUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agentApplicationApi),
    })
}

export const getAgentApplicationsEnvPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/env/`
}

/**
 * PUT: replace the entire env. PATCH: merge individual keys (set to null to remove).
 */
export const agentApplicationsEnvPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAgentApplicationApi?: NonReadonly<PatchedAgentApplicationApi>,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsEnvPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAgentApplicationApi),
    })
}

export const getAgentApplicationsPreviewCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/preview/`
}

/**
 * Mark a ready revision as preview. Blocked if required secrets are missing.
 */
export const agentApplicationsPreviewCreate = async (
    projectId: string,
    id: string,
    previewRevisionRequestApi: PreviewRevisionRequestApi,
    options?: RequestInit
): Promise<AgentApplicationRevisionApi> => {
    return apiMutator<AgentApplicationRevisionApi>(getAgentApplicationsPreviewCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(previewRevisionRequestApi),
    })
}

export const getAgentApplicationsPromoteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/promote/`
}

/**
 * Promote a ready revision to live. Blocked if required secrets are missing.
 */
export const agentApplicationsPromoteCreate = async (
    projectId: string,
    id: string,
    promoteRevisionRequestApi: PromoteRevisionRequestApi,
    options?: RequestInit
): Promise<AgentApplicationRevisionApi> => {
    return apiMutator<AgentApplicationRevisionApi>(getAgentApplicationsPromoteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(promoteRevisionRequestApi),
    })
}

export const getAgentApplicationsStartDeployCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/start_deploy/`
}

/**
 * Create a pending revision and return a presigned upload target.
 */
export const agentApplicationsStartDeployCreate = async (
    projectId: string,
    id: string,
    startDeployRequestApi: StartDeployRequestApi,
    options?: RequestInit
): Promise<StartDeployResponseApi> => {
    return apiMutator<StartDeployResponseApi>(getAgentApplicationsStartDeployCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(startDeployRequestApi),
    })
}
