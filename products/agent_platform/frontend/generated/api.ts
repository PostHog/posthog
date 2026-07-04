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
    AgentAggregateStatsApi,
    AgentApplicationApi,
    AgentApplicationApprovalsListResponseApi,
    AgentApplicationPreviewTokenResponseApi,
    AgentApplicationSessionLogsResponseApi,
    AgentApplicationSessionsListResponseApi,
    AgentApplicationSessionsRetrieveResponseApi,
    AgentApplicationsApprovalsListParams,
    AgentApplicationsListParams,
    AgentApplicationsPreviewProxyGetParams,
    AgentApplicationsPreviewProxyParams,
    AgentApplicationsPreviewTokenMintParams,
    AgentApplicationsPreviewTokenParams,
    AgentApplicationsRevisionsListParams,
    AgentApplicationsSessionLogsParams,
    AgentApplicationsSessionsListParams,
    AgentApplicationsSessionsRetrieveParams,
    AgentApplicationsSpecSchemaParams,
    AgentApplicationsStatsParams,
    AgentApprovalsDecideResponseApi,
    AgentFleetApprovalsListParams,
    AgentFleetLiveSessionsParams,
    AgentFleetLiveSessionsResponseApi,
    AgentFleetStatsParams,
    AgentMemoryDeleteFileParams,
    AgentMemoryFileApi,
    AgentMemoryGetFileParams,
    AgentMemoryListFilesParams,
    AgentMemoryListResponseApi,
    AgentMemoryReadTableParams,
    AgentMemorySearchParams,
    AgentMemorySearchResponseApi,
    AgentMemoryTreeResponseApi,
    AgentMemoryUpdateFileParams,
    AgentMemoryWriteRequestApi,
    AgentNativeToolsListResponseApi,
    AgentRevisionApi,
    AgentRevisionCronFireRequestApi,
    AgentRevisionCronFireResponseApi,
    AgentRevisionEnvKeyStatusApi,
    AgentRevisionEnvKeysResponseApi,
    AgentRevisionSlackManifestResponseApi,
    AgentRevisionSystemPromptResponseApi,
    AgentRevisionValidateResponseApi,
    AgentTableRowsResponseApi,
    AgentTablesListResponseApi,
    AgentUsersListApi,
    CloneFromRequestApi,
    DecideApprovalRequestApi,
    NewDraftRevisionRequestApi,
    PaginatedAgentApplicationListApi,
    PaginatedAgentRevisionSummaryListApi,
    PatchedAgentApplicationApi,
    PatchedAgentMemoryUpdateRequestApi,
    PatchedAgentRevisionApi,
    PreviewProxyInvokeRequestApi,
    SetEnvKeyRequestApi,
    SetEnvRequestApi,
    SetSkillRefsRequestApi,
    WriteAgentMdRequestApi,
    WriteSpecRequestApi,
    WriteToolRequestApi,
    WriteTypedBundleRequestApi,
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/`
}

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

export const getAgentMemoryListFilesUrl = (
    projectId: string,
    applicationId: string,
    params?: AgentMemoryListFilesParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/`
}

/**
 * List memory file headers under the agent's prefix. Headers only — no bodies.
 */
export const agentMemoryListFiles = async (
    projectId: string,
    applicationId: string,
    params?: AgentMemoryListFilesParams,
    options?: RequestInit
): Promise<AgentMemoryListResponseApi> => {
    return apiMutator<AgentMemoryListResponseApi>(getAgentMemoryListFilesUrl(projectId, applicationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryCreateFileUrl = (projectId: string, applicationId: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/`
}

/**
 * Create a memory file. Fails if the path already exists — use the update endpoint to overwrite.
 */
export const agentMemoryCreateFile = async (
    projectId: string,
    applicationId: string,
    agentMemoryWriteRequestApi: AgentMemoryWriteRequestApi,
    options?: RequestInit
): Promise<AgentMemoryFileApi> => {
    return apiMutator<AgentMemoryFileApi>(getAgentMemoryCreateFileUrl(projectId, applicationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agentMemoryWriteRequestApi),
    })
}

export const getAgentMemoryGetFileUrl = (
    projectId: string,
    applicationId: string,
    params: AgentMemoryGetFileParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/by_path/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/by_path/`
}

/**
 * Read one memory file in full (frontmatter + markdown body).
 */
export const agentMemoryGetFile = async (
    projectId: string,
    applicationId: string,
    params: AgentMemoryGetFileParams,
    options?: RequestInit
): Promise<AgentMemoryFileApi> => {
    return apiMutator<AgentMemoryFileApi>(getAgentMemoryGetFileUrl(projectId, applicationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryUpdateFileUrl = (
    projectId: string,
    applicationId: string,
    params: AgentMemoryUpdateFileParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/by_path/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/by_path/`
}

/**
 * Update a memory file. Any field omitted is preserved from the existing file.
 */
export const agentMemoryUpdateFile = async (
    projectId: string,
    applicationId: string,
    params: AgentMemoryUpdateFileParams,
    patchedAgentMemoryUpdateRequestApi?: PatchedAgentMemoryUpdateRequestApi,
    options?: RequestInit
): Promise<AgentMemoryFileApi> => {
    return apiMutator<AgentMemoryFileApi>(getAgentMemoryUpdateFileUrl(projectId, applicationId, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAgentMemoryUpdateRequestApi),
    })
}

export const getAgentMemoryDeleteFileUrl = (
    projectId: string,
    applicationId: string,
    params: AgentMemoryDeleteFileParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/by_path/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/memory/files/by_path/`
}

/**
 * Hard-delete a memory file. Activity log captures the action against the agent.
 */
export const agentMemoryDeleteFile = async (
    projectId: string,
    applicationId: string,
    params: AgentMemoryDeleteFileParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentMemoryDeleteFileUrl(projectId, applicationId, params), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentMemorySearchUrl = (projectId: string, applicationId: string, params: AgentMemorySearchParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/memory/search/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/memory/search/`
}

/**
 * BM25 search across the agent's memory files. Ranks by description+tags+path+body with field weighting.
 */
export const agentMemorySearch = async (
    projectId: string,
    applicationId: string,
    params: AgentMemorySearchParams,
    options?: RequestInit
): Promise<AgentMemorySearchResponseApi> => {
    return apiMutator<AgentMemorySearchResponseApi>(getAgentMemorySearchUrl(projectId, applicationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryListTablesUrl = (projectId: string, applicationId: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/memory/tables/`
}

/**
 * List the agent's tabular-reference tables (the @posthog/table-* JSONL tables): name + byte size.
 */
export const agentMemoryListTables = async (
    projectId: string,
    applicationId: string,
    options?: RequestInit
): Promise<AgentTablesListResponseApi> => {
    return apiMutator<AgentTablesListResponseApi>(getAgentMemoryListTablesUrl(projectId, applicationId), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryReadTableUrl = (
    projectId: string,
    applicationId: string,
    name: string,
    params?: AgentMemoryReadTableParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/memory/tables/${name}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/memory/tables/${name}/`
}

/**
 * Read rows from one tabular-reference table (capped via ?limit).
 */
export const agentMemoryReadTable = async (
    projectId: string,
    applicationId: string,
    name: string,
    params?: AgentMemoryReadTableParams,
    options?: RequestInit
): Promise<AgentTableRowsResponseApi> => {
    return apiMutator<AgentTableRowsResponseApi>(getAgentMemoryReadTableUrl(projectId, applicationId, name, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryTreeUrl = (projectId: string, applicationId: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/memory/tree/`
}

/**
 * Pre-aggregated folder tree of memory files. Saves the frontend re-derivation work.
 */
export const agentMemoryTree = async (
    projectId: string,
    applicationId: string,
    options?: RequestInit
): Promise<AgentMemoryTreeResponseApi> => {
    return apiMutator<AgentMemoryTreeResponseApi>(getAgentMemoryTreeUrl(projectId, applicationId), {
        ...options,
        method: 'GET',
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsList = async (
    projectId: string,
    applicationId: string,
    params?: AgentApplicationsRevisionsListParams,
    options?: RequestInit
): Promise<PaginatedAgentRevisionSummaryListApi> => {
    return apiMutator<PaginatedAgentRevisionSummaryListApi>(
        getAgentApplicationsRevisionsListUrl(projectId, applicationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRevisionsCreateUrl = (projectId: string, applicationId: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsCreate = async (
    projectId: string,
    applicationId: string,
    agentRevisionApi?: NonReadonly<AgentRevisionApi>,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsCreateUrl(projectId, applicationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agentRevisionApi),
    })
}

export const getAgentApplicationsRevisionsRetrieveUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsRetrieve = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsRetrieveUrl(projectId, applicationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsRevisionsUpdateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/`
}

/**
 * Spec edits are only allowed while state='draft'. Once promoted to
 * ready/live the spec is frozen — change requires a new revision.
 */
export const agentApplicationsRevisionsUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    agentRevisionApi?: NonReadonly<AgentRevisionApi>,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agentRevisionApi),
    })
}

export const getAgentApplicationsRevisionsPartialUpdateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsPartialUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    patchedAgentRevisionApi?: NonReadonly<PatchedAgentRevisionApi>,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsPartialUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAgentRevisionApi),
    })
}

export const getAgentApplicationsRevisionsDestroyUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsDestroy = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsRevisionsDestroyUrl(projectId, applicationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsRevisionsAgentMdUpdateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/agent_md/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsAgentMdUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    writeAgentMdRequestApi: WriteAgentMdRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsAgentMdUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(writeAgentMdRequestApi),
    })
}

export const getAgentApplicationsRevisionsArchiveCreateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/archive/`
}

/**
 * Mark a revision archived. If it was the live one, clear the
 * application's live_revision pointer (the app effectively has no
 * deployable version until another revision is promoted).
 */
export const agentApplicationsRevisionsArchiveCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsArchiveCreateUrl(projectId, applicationId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgentApplicationsRevisionsBundleRetrieveUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/bundle/`
}

/**
 * Read the full typed bundle: `{ agent_md, skills, tools, spec }`.
 */
export const agentApplicationsRevisionsBundleRetrieve = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsBundleRetrieveUrl(projectId, applicationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsRevisionsBundleUpdateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/bundle/`
}

/**
 * Full-replace the typed bundle. Anything not in the payload is
 * deleted. Tool sources are AST-checked + esbuild-compiled by the
 * janitor before any S3 writes.
 */
export const agentApplicationsRevisionsBundleUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    writeTypedBundleRequestApi: WriteTypedBundleRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsBundleUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(writeTypedBundleRequestApi),
    })
}

export const getAgentApplicationsRevisionsCloneFromCreateUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/clone_from/`
}

/**
 * Copy every file from `source_revision_id` into this revision.
 */
export const agentApplicationsRevisionsCloneFromCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    cloneFromRequestApi: CloneFromRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsCloneFromCreateUrl(projectId, applicationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cloneFromRequestApi),
    })
}

export const getAgentApplicationsRevisionsCronFireCreateUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/cron/fire/`
}

/**
 * Fire one cron job out-of-band — the same execution path the
 * scheduler walks, but on demand. Authoring UX: the user iterates on
 * a cron prompt by clicking 'Fire now' rather than waiting for the
 * next scheduled firing. Without this, 'did my prompt do the right
 * thing?' is unanswerable until the cron actually fires.
 *
 * Idempotent via `request_id`: repeat clicks with the same id resolve
 * to the same session id rather than firing N times.
 */
export const agentApplicationsRevisionsCronFireCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    agentRevisionCronFireRequestApi: AgentRevisionCronFireRequestApi,
    options?: RequestInit
): Promise<AgentRevisionCronFireResponseApi> => {
    return apiMutator<AgentRevisionCronFireResponseApi>(
        getAgentApplicationsRevisionsCronFireCreateUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(agentRevisionCronFireRequestApi),
        }
    )
}

export const getAgentRevisionsEnvKeysListUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/env_keys/`
}

/**
 * List the names of secrets currently set on this revision.
 *
 * Returns names only — values stay server-side under
 * `EncryptedTextField`. Use this to drive the "set / unset" badge next to
 * a declared secret in the editor UI.
 */
export const agentRevisionsEnvKeysList = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionEnvKeysResponseApi> => {
    return apiMutator<AgentRevisionEnvKeysResponseApi>(getAgentRevisionsEnvKeysListUrl(projectId, applicationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgentRevisionsEnvKeysGetUrl = (projectId: string, applicationId: string, id: string, key: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/env_keys/${key}/`
}

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const agentRevisionsEnvKeysGet = async (
    projectId: string,
    applicationId: string,
    id: string,
    key: string,
    options?: RequestInit
): Promise<AgentRevisionEnvKeyStatusApi> => {
    return apiMutator<AgentRevisionEnvKeyStatusApi>(getAgentRevisionsEnvKeysGetUrl(projectId, applicationId, id, key), {
        ...options,
        method: 'GET',
    })
}

export const getAgentRevisionsEnvKeysSetUrl = (projectId: string, applicationId: string, id: string, key: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/env_keys/${key}/`
}

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const agentRevisionsEnvKeysSet = async (
    projectId: string,
    applicationId: string,
    id: string,
    key: string,
    setEnvKeyRequestApi: SetEnvKeyRequestApi,
    options?: RequestInit
): Promise<AgentRevisionEnvKeyStatusApi> => {
    return apiMutator<AgentRevisionEnvKeyStatusApi>(getAgentRevisionsEnvKeysSetUrl(projectId, applicationId, id, key), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setEnvKeyRequestApi),
    })
}

export const getAgentRevisionsEnvKeysClearUrl = (projectId: string, applicationId: string, id: string, key: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/env_keys/${key}/`
}

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const agentRevisionsEnvKeysClear = async (
    projectId: string,
    applicationId: string,
    id: string,
    key: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentRevisionsEnvKeysClearUrl(projectId, applicationId, id, key), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsRevisionsFreezeCreateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/freeze/`
}

/**
 * Freeze the bundle: draft → ready, stamps sha256 on the row.
 *
 * Django is a thin proxy here: resolve template refs into the
 * bundle, ask the janitor to seal it (the janitor returns the sha
 * + the spec it derived from the typed resources), then stamp the
 * row. No `transaction.atomic()` — the janitor's freeze is idempotent
 * (on retry it re-reads the existing `.frozen` marker + re-derives
 * spec), so a partial failure here is recoverable by re-calling
 * freeze, not by transactional rollback. Holding an atomic block
 * across the janitor HTTP call previously deadlocked the
 * agent_revision row against the janitor's spec write — that's
 * moved off the janitor side as part of the same fix.
 */
export const agentApplicationsRevisionsFreezeCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsFreezeCreateUrl(projectId, applicationId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgentApplicationsRevisionsManifestRetrieveUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/manifest/`
}

/**
 * List every file in this revision's bundle (path, size, sha256).
 */
export const agentApplicationsRevisionsManifestRetrieve = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(
        getAgentApplicationsRevisionsManifestRetrieveUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRevisionsPromoteCreateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/promote/`
}

/**
 * ready → live. Sets the parent application's live_revision.
 */
export const agentApplicationsRevisionsPromoteCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsPromoteCreateUrl(projectId, applicationId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgentApplicationsRevisionsSetEnvCreateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/set_env/`
}

/**
 * Replace this revision's encrypted env block.
 *
 * The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
 * text is stored on `AgentRevision.encrypted_env`; the worker decrypts it
 * at session start via the same Fernet schedule (see
 * agent-shared/src/runtime/encryption.ts).
 */
export const agentApplicationsRevisionsSetEnvCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    setEnvRequestApi: SetEnvRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsSetEnvCreateUrl(projectId, applicationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setEnvRequestApi),
    })
}

export const getAgentApplicationsRevisionsSkillRefsUpdateUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/skill_refs/`
}

/**
 * Full-replace the draft's store-skill references. They are resolved
 * and materialized into the bundle at freeze, not here — this only records
 * which skills (and pinned versions) the freeze should pull in.
 */
export const agentApplicationsRevisionsSkillRefsUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    setSkillRefsRequestApi: SetSkillRefsRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsSkillRefsUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setSkillRefsRequestApi),
    })
}

export const getAgentApplicationsRevisionsSlackManifestUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/slack_manifest/`
}

/**
 * Build a Slack app manifest for this revision's slack trigger.
 *
 * Deterministic: the OAuth scopes and bot event subscriptions are derived
 * from the slack trigger config (`mention_only` / `auto_resume_threads` /
 * `ack_reaction`) and the agent's Slack tools, so the manifest already
 * subscribes to exactly the events the config needs. 400 if the revision
 * has no slack trigger.
 */
export const agentApplicationsRevisionsSlackManifest = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionSlackManifestResponseApi> => {
    return apiMutator<AgentRevisionSlackManifestResponseApi>(
        getAgentApplicationsRevisionsSlackManifestUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRevisionsSpecUpdateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/spec/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsSpecUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    writeSpecRequestApi: WriteSpecRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsSpecUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(writeSpecRequestApi),
    })
}

export const getAgentApplicationsRevisionsSystemPromptUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/system_prompt/`
}

/**
 * Return the fully-assembled system prompt for this revision.
 *
 * Authoring tools call this to preview what the model will actually
 * see at session start — the platform framework preamble plus the
 * bundle's `agent.md` plus the skills index. Useful for debugging
 * author-vs-framework precedence conflicts and verifying
 * `spec.framework_prompt.omit` overrides took effect.
 */
export const agentApplicationsRevisionsSystemPrompt = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionSystemPromptResponseApi> => {
    return apiMutator<AgentRevisionSystemPromptResponseApi>(
        getAgentApplicationsRevisionsSystemPromptUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRevisionsToolsUpdateUrl = (
    projectId: string,
    applicationId: string,
    id: string,
    toolId: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/tools/${toolId}/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsToolsUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    toolId: string,
    writeToolRequestApi: WriteToolRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(
        getAgentApplicationsRevisionsToolsUpdateUrl(projectId, applicationId, id, toolId),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(writeToolRequestApi),
        }
    )
}

export const getAgentApplicationsRevisionsToolsDestroyUrl = (
    projectId: string,
    applicationId: string,
    id: string,
    toolId: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/tools/${toolId}/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsToolsDestroy = async (
    projectId: string,
    applicationId: string,
    id: string,
    toolId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsRevisionsToolsDestroyUrl(projectId, applicationId, id, toolId), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsRevisionsValidateCreateUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/validate/`
}

/**
 * Pre-flight checks before freeze + promote: agent.md exists,
 * every native tool id is registered, every custom tool has its
 * compiled.js + schema.json, every skill path exists, every declared
 * secret has a value set in this revision's env block. Returns
 * `{ ok, errors: [...] }`. Works on any revision state.
 */
export const agentApplicationsRevisionsValidateCreate = async (
    projectId: string,
    applicationId: string,
    id: string,
    options?: RequestInit
): Promise<AgentRevisionValidateResponseApi> => {
    return apiMutator<AgentRevisionValidateResponseApi>(
        getAgentApplicationsRevisionsValidateCreateUrl(projectId, applicationId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getAgentApplicationsRevisionsNewDraftCreateUrl = (projectId: string, applicationId: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/new_draft/`
}

/**
 * Create a fresh draft revision under `application_id` and seed it
 * from `source_revision_id`. Saves the MCP one round-trip vs the
 * explicit create + clone_from sequence.
 */
export const agentApplicationsRevisionsNewDraftCreate = async (
    projectId: string,
    applicationId: string,
    newDraftRevisionRequestApi: NewDraftRevisionRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsNewDraftCreateUrl(projectId, applicationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(newDraftRevisionRequestApi),
    })
}

export const getAgentApplicationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/`
}

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsApprovalsListUrl = (
    projectId: string,
    id: string,
    params?: AgentApplicationsApprovalsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/approvals/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/approvals/`
}

/**
 * List approval-gated tool requests for this application. Team-admin
 * only (per plan §6.1). Default returns all states — pass `?state=queued`
 * for the inbox view.
 */
export const agentApplicationsApprovalsList = async (
    projectId: string,
    id: string,
    params?: AgentApplicationsApprovalsListParams,
    options?: RequestInit
): Promise<AgentApplicationApprovalsListResponseApi> => {
    return apiMutator<AgentApplicationApprovalsListResponseApi>(
        getAgentApplicationsApprovalsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsApprovalsRetrieveUrl = (projectId: string, id: string, approvalId: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/approvals/${approvalId}/`
}

/**
 * Single approval request — full proposed args, assistant snapshot,
 * decision metadata, dispatch outcome. Team-admin only (plan §6.1).
 */
export const agentApplicationsApprovalsRetrieve = async (
    projectId: string,
    id: string,
    approvalId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsApprovalsRetrieveUrl(projectId, id, approvalId), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsApprovalsDecideUrl = (projectId: string, id: string, approvalId: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/approvals/${approvalId}/decide/`
}

/**
 * Approve or reject a queued `agent`-type tool-approval request.
 *
 * This is the OWNER decision surface — the only PostHog-authoritative one:
 * team admins decide here, in the console. `principal`-type approvals are
 * decided by the session principal at the ingress decision API, not here.
 * The runtime side runs the tool platform-side on approve and wakes the
 * session with a synthetic tool_result either way.
 */
export const agentApplicationsApprovalsDecide = async (
    projectId: string,
    id: string,
    approvalId: string,
    decideApprovalRequestApi: DecideApprovalRequestApi,
    options?: RequestInit
): Promise<AgentApprovalsDecideResponseApi> => {
    return apiMutator<AgentApprovalsDecideResponseApi>(
        getAgentApplicationsApprovalsDecideUrl(projectId, id, approvalId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(decideApprovalRequestApi),
        }
    )
}

export const getAgentApplicationsPreviewProxyGetUrl = (
    projectId: string,
    id: string,
    rest: string,
    params: AgentApplicationsPreviewProxyGetParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/preview-proxy/${rest}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/preview-proxy/${rest}/`
}

/**
 * GET passthrough for the preview-proxy — used for `/listen` SSE.
 */
export const agentApplicationsPreviewProxyGet = async (
    projectId: string,
    id: string,
    rest: string,
    params: AgentApplicationsPreviewProxyGetParams,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsPreviewProxyGetUrl(projectId, id, rest, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsPreviewProxyUrl = (
    projectId: string,
    id: string,
    rest: string,
    params: AgentApplicationsPreviewProxyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/preview-proxy/${rest}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/preview-proxy/${rest}/`
}

/**
 * Authoring-side proxy for invoking a *draft* (or any non-live) revision.
 *
 * Closes the anonymous-draft-invoke gap: the public ingress URL refuses
 * non-live invokes that don't carry the `x-agent-preview-secret` header;
 * this proxy attaches it after authenticating the Django caller.
 *
 * URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
 * Auth: standard PAT / session — `agents:write` scope (POST run/send/cancel
 * is a mutating invoke; the read-only `listen` GET is `agents:read`).
 */
export const agentApplicationsPreviewProxy = async (
    projectId: string,
    id: string,
    rest: string,
    params: AgentApplicationsPreviewProxyParams,
    previewProxyInvokeRequestApi?: PreviewProxyInvokeRequestApi,
    options?: RequestInit
): Promise<string> => {
    return apiMutator<string>(getAgentApplicationsPreviewProxyUrl(projectId, id, rest, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(previewProxyInvokeRequestApi),
    })
}

export const getAgentApplicationsPreviewTokenUrl = (
    projectId: string,
    id: string,
    params: AgentApplicationsPreviewTokenParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/preview-token/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/preview-token/`
}

/**
 * GET sibling of `preview_token_mint`. Same body and response
 * shape — exists because `EventSource` can't set headers, so SSE
 * callers fetch the token via GET and then attach `?preview_token=`
 * to the ingress URL. Behind the same URL (`url_path="preview-token"`)
 * thanks to DRF's `@<action>.mapping.get`; DRF resolves it to a
 * distinct `view.action`, but it is in `scope_object_write_actions`
 * alongside the POST sibling — both return a usable credential, so
 * both require `agents:write`.
 */
export const agentApplicationsPreviewToken = async (
    projectId: string,
    id: string,
    params: AgentApplicationsPreviewTokenParams,
    options?: RequestInit
): Promise<AgentApplicationPreviewTokenResponseApi> => {
    return apiMutator<AgentApplicationPreviewTokenResponseApi>(
        getAgentApplicationsPreviewTokenUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsPreviewTokenMintUrl = (
    projectId: string,
    id: string,
    params: AgentApplicationsPreviewTokenMintParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/preview-token/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/preview-token/`
}

/**
 * Mint a short-lived JWT for talking to a non-live revision
 * directly via the public ingress URL. The caller attaches it as
 * the `x-agent-preview-token` header (or `?preview_token=` query
 * param for `EventSource`). See `_mint_preview_jwt` for the
 * payload + claim binding.
 *
 * The response also includes `endpoints`, `auth`, and
 * `preview_proxy` blocks so the caller can wire a preview
 * invocation without grepping the agent-ingress source for which
 * path each trigger exposes or which header name carries the
 * token. This is the "self-describing" half of preview-mode —
 * every piece of info you need to hit ingress is in one response.
 *
 * POST is the canonical verb — minting credentials for downstream
 * `run`/`send`/`cancel` is a write-class capability. A GET sibling
 * exists at the same URL for `EventSource` callers (which can't set
 * headers); it is also write-scoped, since it returns the same token.
 */
export const agentApplicationsPreviewTokenMint = async (
    projectId: string,
    id: string,
    params: AgentApplicationsPreviewTokenMintParams,
    options?: RequestInit
): Promise<AgentApplicationPreviewTokenResponseApi> => {
    return apiMutator<AgentApplicationPreviewTokenResponseApi>(
        getAgentApplicationsPreviewTokenMintUrl(projectId, id, params),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getAgentApplicationsSessionsListUrl = (
    projectId: string,
    id: string,
    params?: AgentApplicationsSessionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/sessions/`
}

/**
 * List sessions for this application, newest first. Strips the
 * conversation transcript from each summary, but includes a `preview`
 * (last assistant text, ~120 chars) and `usage_total` (token + cost
 * aggregate). Use `agent-applications-sessions-retrieve` for the full
 * transcript of a single session.
 */
export const agentApplicationsSessionsList = async (
    projectId: string,
    id: string,
    params?: AgentApplicationsSessionsListParams,
    options?: RequestInit
): Promise<AgentApplicationSessionsListResponseApi> => {
    return apiMutator<AgentApplicationSessionsListResponseApi>(
        getAgentApplicationsSessionsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsSessionsRetrieveUrl = (
    projectId: string,
    id: string,
    sessionId: string,
    params?: AgentApplicationsSessionsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/`
}

/**
 * Fetch one session's state — full conversation by default, or just
 * the trailing N messages with `?last_n=`. Always returns a
 * `usage_total` block aggregated over the entire session, regardless of
 * trim. The runner-side queue DB is the source of truth.
 */
export const agentApplicationsSessionsRetrieve = async (
    projectId: string,
    id: string,
    sessionId: string,
    params?: AgentApplicationsSessionsRetrieveParams,
    options?: RequestInit
): Promise<AgentApplicationSessionsRetrieveResponseApi> => {
    return apiMutator<AgentApplicationSessionsRetrieveResponseApi>(
        getAgentApplicationsSessionsRetrieveUrl(projectId, id, sessionId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsSessionLogsUrl = (
    projectId: string,
    id: string,
    sessionId: string,
    params?: AgentApplicationsSessionLogsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/logs/`
}

/**
 * Read the runner's structured event log for one session from
 * ClickHouse. Filters (limit / after / before / level / search)
 * match the shared `LogEntryMixin` helper used by hog_function +
 * hog_flow.
 */
export const agentApplicationsSessionLogs = async (
    projectId: string,
    id: string,
    sessionId: string,
    params?: AgentApplicationsSessionLogsParams,
    options?: RequestInit
): Promise<AgentApplicationSessionLogsResponseApi> => {
    return apiMutator<AgentApplicationSessionLogsResponseApi>(
        getAgentApplicationsSessionLogsUrl(projectId, id, sessionId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsStatsUrl = (projectId: string, id: string, params?: AgentApplicationsStatsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/stats/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/stats/`
}

/**
 * Roll-up stats for the agent — drives the agent-detail overview tiles.
 */
export const agentApplicationsStats = async (
    projectId: string,
    id: string,
    params?: AgentApplicationsStatsParams,
    options?: RequestInit
): Promise<AgentAggregateStatsApi> => {
    return apiMutator<AgentAggregateStatsApi>(getAgentApplicationsStatsUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsUsersListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/users/`
}

/**
 * List this agent's end-users (the stable identities behind inbound principals) and each user's linked external connections. Connection metadata only — credential material is never returned.
 */
export const agentApplicationsUsersList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgentUsersListApi> => {
    return apiMutator<AgentUsersListApi>(getAgentApplicationsUsersListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsUsersConnectionDeleteUrl = (
    projectId: string,
    id: string,
    agentUserId: string,
    provider: string
) => {
    return `/api/projects/${projectId}/agent_applications/${id}/users/${agentUserId}/connections/${provider}/`
}

/**
 * Revoke one of an end-user's linked connections. The credential is marked revoked (kept for audit), so the agent can no longer act as that user on the provider.
 */
export const agentApplicationsUsersConnectionDelete = async (
    projectId: string,
    id: string,
    agentUserId: string,
    provider: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsUsersConnectionDeleteUrl(projectId, id, agentUserId, provider), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsModelsUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_applications/models/`
}

/**
 * Served-model catalog — each model's id, provider, context window, and USD-per-million-token pricing — plus the curated auto-level → model map. Project-agnostic; sourced from the AI gateway catalog. Powers the config UI model browser and the agent builder's model-choosing skill.
 */
export const agentApplicationsModels = async (
    projectId: string,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsModelsUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsSpecSchemaUrl = (projectId: string, params?: AgentApplicationsSpecSchemaParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/spec_schema/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/spec_schema/`
}

/**
 * The canonical JSON Schema for an agent `spec` — every field, type, enum, default, and the discriminated unions for `models` / `triggers[]` / `tools[]`, each with an inline description. Emitted from the same source the runner validates against (fields with a default are optional on write), so read it BEFORE composing a spec for create / revisions-spec-update instead of guessing the shape. Pass `section` to fetch just one part.
 */
export const agentApplicationsSpecSchema = async (
    projectId: string,
    params?: AgentApplicationsSpecSchemaParams,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsSpecSchemaUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentFleetApprovalsListUrl = (projectId: string, params?: AgentFleetApprovalsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_fleet/approvals/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_fleet/approvals/`
}

/**
 * Approval-gated tool requests across every agent in this team. Team-admin only.
 */
export const agentFleetApprovalsList = async (
    projectId: string,
    params?: AgentFleetApprovalsListParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentFleetApprovalsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentFleetLiveSessionsUrl = (projectId: string, params?: AgentFleetLiveSessionsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_fleet/live_sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_fleet/live_sessions/`
}

/**
 * Live (non-terminal) sessions across every agent owned by this team, newest activity first.
 */
export const agentFleetLiveSessions = async (
    projectId: string,
    params?: AgentFleetLiveSessionsParams,
    options?: RequestInit
): Promise<AgentFleetLiveSessionsResponseApi> => {
    return apiMutator<AgentFleetLiveSessionsResponseApi>(getAgentFleetLiveSessionsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentFleetStatsUrl = (projectId: string, params?: AgentFleetStatsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_fleet/stats/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_fleet/stats/`
}

/**
 * Roll-up stats across every agent owned by this team.
 */
export const agentFleetStats = async (
    projectId: string,
    params?: AgentFleetStatsParams,
    options?: RequestInit
): Promise<AgentAggregateStatsApi> => {
    return apiMutator<AgentAggregateStatsApi>(getAgentFleetStatsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentNativeToolsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_native_tools/`
}

/**
 * Read-only catalog of every @posthog/* native tool the runner knows.
 */
export const agentNativeToolsList = async (
    projectId: string,
    options?: RequestInit
): Promise<AgentNativeToolsListResponseApi[]> => {
    return apiMutator<AgentNativeToolsListResponseApi[]>(getAgentNativeToolsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
