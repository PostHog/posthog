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
    AgentApplicationEnvKeyStatusApi,
    AgentApplicationEnvKeysResponseApi,
    AgentApplicationPreviewTokenResponseApi,
    AgentApplicationSessionLogsResponseApi,
    AgentApplicationSessionsListResponseApi,
    AgentApplicationSessionsRetrieveResponseApi,
    AgentApplicationsApprovalsListParams,
    AgentApplicationsListParams,
    AgentApplicationsPreviewProxyGetParams,
    AgentApplicationsPreviewProxyParams,
    AgentApplicationsPreviewTokenParams,
    AgentApplicationsRevisionsFileDestroyParams,
    AgentApplicationsRevisionsFileRetrieveParams,
    AgentApplicationsRevisionsFileUpdateParams,
    AgentApplicationsRevisionsListParams,
    AgentApplicationsSessionLogsParams,
    AgentApplicationsSessionsListParams,
    AgentApplicationsSessionsRetrieveParams,
    AgentApplicationsStatsParams,
    AgentApprovalsDecideResponseApi,
    AgentCustomToolTemplatesListParams,
    AgentCustomToolTemplatesNameRetrieveParams,
    AgentCustomToolTemplatesNameUsagesListParams,
    AgentFleetLiveSessionsParams,
    AgentFleetLiveSessionsResponseApi,
    AgentFleetStatsParams,
    AgentMemoryDeleteFileParams,
    AgentMemoryFileApi,
    AgentMemoryGetFileParams,
    AgentMemoryListFilesParams,
    AgentMemoryListResponseApi,
    AgentMemorySearchParams,
    AgentMemorySearchResponseApi,
    AgentMemoryTreeResponseApi,
    AgentMemoryUpdateFileParams,
    AgentMemoryWriteRequestApi,
    AgentNativeToolsListResponseApi,
    AgentRevisionApi,
    AgentRevisionCronFireRequestApi,
    AgentRevisionCronFireResponseApi,
    AgentRevisionSystemPromptResponseApi,
    AgentRevisionValidateResponseApi,
    AgentSkillTemplatesListParams,
    AgentSkillTemplatesNameRetrieveParams,
    AgentSkillTemplatesNameUsagesListParams,
    CloneFromRequestApi,
    CustomToolTemplateCreateApi,
    CustomToolTemplateDetailApi,
    CustomToolTemplateDuplicateApi,
    CustomToolTemplatePublishApi,
    CustomToolTemplateSummaryApi,
    CustomToolTemplateUsageApi,
    DecideApprovalRequestApi,
    NewDraftRevisionRequestApi,
    PaginatedAgentApplicationListApi,
    PaginatedAgentRevisionListApi,
    PatchedAgentApplicationApi,
    PatchedAgentMemoryUpdateRequestApi,
    PatchedAgentRevisionApi,
    SetEnvKeyRequestApi,
    SetEnvRequestApi,
    SkillTemplateCreateApi,
    SkillTemplateDetailApi,
    SkillTemplateDuplicateApi,
    SkillTemplateFileApi,
    SkillTemplateFileRenameApi,
    SkillTemplateFileWriteApi,
    SkillTemplatePublishApi,
    SkillTemplateSummaryApi,
    SkillTemplateUsageApi,
    TemplateVersionEntryApi,
    WriteBundleRequestApi,
    WriteFileRequestApi,
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
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/`
}

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsList = async (
    projectId: string,
    applicationId: string,
    params?: AgentApplicationsRevisionsListParams,
    options?: RequestInit
): Promise<PaginatedAgentRevisionListApi> => {
    return apiMutator<PaginatedAgentRevisionListApi>(
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
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
ready/live the spec is frozen — change requires a new revision.
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
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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

export const getAgentApplicationsRevisionsArchiveCreateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/archive/`
}

/**
 * Mark a revision archived. If it was the live one, clear the
application's live_revision pointer (the app effectively has no
deployable version until another revision is promoted).
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
 * Bulk-pull: returns `{ files: { path: content, ... }, ... }`. Use
this when the MCP wants the whole bundle to work on locally.
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
 * Bulk-push the bundle. Body `{ files, mode: replace|merge }`.
 */
export const agentApplicationsRevisionsBundleUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    writeBundleRequestApi: WriteBundleRequestApi,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(getAgentApplicationsRevisionsBundleUpdateUrl(projectId, applicationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(writeBundleRequestApi),
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
scheduler walks, but on demand. Authoring UX: the user iterates on
a cron prompt by clicking 'Fire now' rather than waiting for the
next scheduled firing. Without this, 'did my prompt do the right
thing?' is unanswerable until the cron actually fires.

Idempotent via `request_id`: repeat clicks with the same id resolve
to the same session id rather than firing N times. See
`docs/agent-platform/plans/cron-trigger-scheduler.md` §9.
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

export const getAgentApplicationsRevisionsFileRetrieveUrl = (
    projectId: string,
    applicationId: string,
    id: string,
    params: AgentApplicationsRevisionsFileRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/file/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/file/`
}

/**
 * Read one file by `?path=...`. Works on any revision state.
 */
export const agentApplicationsRevisionsFileRetrieve = async (
    projectId: string,
    applicationId: string,
    id: string,
    params: AgentApplicationsRevisionsFileRetrieveParams,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(
        getAgentApplicationsRevisionsFileRetrieveUrl(projectId, applicationId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentApplicationsRevisionsFileUpdateUrl = (
    projectId: string,
    applicationId: string,
    id: string,
    params: AgentApplicationsRevisionsFileUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/file/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/file/`
}

/**
 * Write one file by `?path=...`. Draft-only (janitor enforces).
 */
export const agentApplicationsRevisionsFileUpdate = async (
    projectId: string,
    applicationId: string,
    id: string,
    writeFileRequestApi: WriteFileRequestApi,
    params: AgentApplicationsRevisionsFileUpdateParams,
    options?: RequestInit
): Promise<AgentRevisionApi> => {
    return apiMutator<AgentRevisionApi>(
        getAgentApplicationsRevisionsFileUpdateUrl(projectId, applicationId, id, params),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(writeFileRequestApi),
        }
    )
}

export const getAgentApplicationsRevisionsFileDestroyUrl = (
    projectId: string,
    applicationId: string,
    id: string,
    params: AgentApplicationsRevisionsFileDestroyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/file/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/file/`
}

/**
 * Delete one file by `?path=...`. Draft-only.
 */
export const agentApplicationsRevisionsFileDestroy = async (
    projectId: string,
    applicationId: string,
    id: string,
    params: AgentApplicationsRevisionsFileDestroyParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsRevisionsFileDestroyUrl(projectId, applicationId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentApplicationsRevisionsFreezeCreateUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/freeze/`
}

/**
 * Freeze the bundle: draft → ready, stamps sha256 on the row.

Resolves `spec.skills[].from_template` / `spec.tools[].from_template`
refs into the bundle (copies content, stamps versions, inserts
join rows) before delegating to the janitor for the sha + state
flip. The Django resolution runs in one `transaction.atomic()` so
a partial freeze leaves the revision in `draft`.
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

export const getAgentApplicationsRevisionsSystemPromptUrl = (projectId: string, applicationId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/system_prompt/`
}

/**
 * Return the fully-assembled system prompt for this revision.

Authoring tools call this to preview what the model will actually
see at session start — the platform framework preamble plus the
bundle's `agent.md` plus the skills index. Useful for debugging
author-vs-framework precedence conflicts and verifying
`spec.framework_prompt.omit` overrides took effect.
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

export const getAgentApplicationsRevisionsValidateCreateUrl = (
    projectId: string,
    applicationId: string,
    id: string
) => {
    return `/api/projects/${projectId}/agent_applications/${applicationId}/revisions/${id}/validate/`
}

/**
 * Pre-flight checks before freeze + promote: entrypoint file exists,
every native tool id is registered, every custom tool has its
compiled.js + schema.json, every skill path exists, every declared
secret has a value set in the application's env block. Returns
`{ ok, errors: [...] }`. Works on any revision state.
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
from `source_revision_id`. Saves the MCP one round-trip vs the
explicit create + clone_from sequence.
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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/approvals/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/approvals/`
}

/**
 * List approval-gated tool requests for this application. Team-admin
only (per plan §6.1). Default returns all states — pass `?state=queued`
for the inbox view.
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
decision metadata, dispatch outcome. Team-admin only (plan §6.1).
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
 * Approve or reject a queued tool-approval request. Team-admin only
(plan §6.1). The runtime side runs the tool platform-side on approve
and wakes the session with a synthetic tool_result either way.
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

export const getAgentApplicationsEnvKeysListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/env_keys/`
}

/**
 * List the names of secrets currently set on the application.

Returns names only — values stay server-side under
`EncryptedTextField`. Use this to drive the "set / unset" badge
next to a declared secret in the editor UI.
 */
export const agentApplicationsEnvKeysList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgentApplicationEnvKeysResponseApi> => {
    return apiMutator<AgentApplicationEnvKeysResponseApi>(getAgentApplicationsEnvKeysListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsEnvKeysGetUrl = (projectId: string, id: string, key: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/env_keys/${key}/`
}

/**
 * GET / PUT / DELETE one secret by name.

- `GET`    → `{ key, is_set }` (never returns the value).
- `PUT`    → upserts `{ value }` into the env block.
- `DELETE` → removes the key. No-op when it wasn't set.

Per-method scope: GET is treated as a write action so the
single action name maps to one consistent scope; reading whether
a secret is set is restricted to writers in any case.
 */
export const agentApplicationsEnvKeysGet = async (
    projectId: string,
    id: string,
    key: string,
    options?: RequestInit
): Promise<AgentApplicationEnvKeyStatusApi> => {
    return apiMutator<AgentApplicationEnvKeyStatusApi>(getAgentApplicationsEnvKeysGetUrl(projectId, id, key), {
        ...options,
        method: 'GET',
    })
}

export const getAgentApplicationsEnvKeysSetUrl = (projectId: string, id: string, key: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/env_keys/${key}/`
}

/**
 * GET / PUT / DELETE one secret by name.

- `GET`    → `{ key, is_set }` (never returns the value).
- `PUT`    → upserts `{ value }` into the env block.
- `DELETE` → removes the key. No-op when it wasn't set.

Per-method scope: GET is treated as a write action so the
single action name maps to one consistent scope; reading whether
a secret is set is restricted to writers in any case.
 */
export const agentApplicationsEnvKeysSet = async (
    projectId: string,
    id: string,
    key: string,
    setEnvKeyRequestApi: SetEnvKeyRequestApi,
    options?: RequestInit
): Promise<AgentApplicationEnvKeyStatusApi> => {
    return apiMutator<AgentApplicationEnvKeyStatusApi>(getAgentApplicationsEnvKeysSetUrl(projectId, id, key), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setEnvKeyRequestApi),
    })
}

export const getAgentApplicationsEnvKeysClearUrl = (projectId: string, id: string, key: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/env_keys/${key}/`
}

/**
 * GET / PUT / DELETE one secret by name.

- `GET`    → `{ key, is_set }` (never returns the value).
- `PUT`    → upserts `{ value }` into the env block.
- `DELETE` → removes the key. No-op when it wasn't set.

Per-method scope: GET is treated as a write action so the
single action name maps to one consistent scope; reading whether
a secret is set is restricted to writers in any case.
 */
export const agentApplicationsEnvKeysClear = async (
    projectId: string,
    id: string,
    key: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentApplicationsEnvKeysClearUrl(projectId, id, key), {
        ...options,
        method: 'DELETE',
    })
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/preview-proxy/${rest}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/preview-proxy/${rest}/`
}

/**
 * Authoring-side proxy for invoking a *draft* (or any non-live) revision.

Closes the anonymous-draft-invoke gap: the public ingress URL refuses
non-live invokes that don't carry the `x-agent-preview-secret` header;
this proxy attaches it after authenticating the Django caller. See
docs/agent-platform/plans/draft-preview-auth.md.

URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
Auth: standard PAT / session — `agent_application:read` scope.
 */
export const agentApplicationsPreviewProxy = async (
    projectId: string,
    id: string,
    rest: string,
    params: AgentApplicationsPreviewProxyParams,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsPreviewProxyUrl(projectId, id, rest, params), {
        ...options,
        method: 'POST',
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/preview-token/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/preview-token/`
}

/**
 * Mint a short-lived JWT for talking to a non-live revision
directly via the public ingress URL. The caller attaches it as
the `x-agent-preview-token` header (or `?preview_token=` query
param for `EventSource`). See `_mint_preview_jwt` for the
payload + claim binding.
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

export const getAgentApplicationsSessionsListUrl = (
    projectId: string,
    id: string,
    params?: AgentApplicationsSessionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/sessions/`
}

/**
 * List sessions for this application, newest first. Strips the
conversation transcript from each summary, but includes a `preview`
(last assistant text, ~120 chars) and `usage_total` (token + cost
aggregate). Use `agent-applications-sessions-retrieve` for the full
transcript of a single session.
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/`
}

/**
 * Fetch one session's state — full conversation by default, or just
the trailing N messages with `?last_n=`. Always returns a
`usage_total` block aggregated over the entire session, regardless of
trim. The runner-side queue DB is the source of truth.
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_applications/${id}/sessions/${sessionId}/logs/`
}

/**
 * Read the runner's structured event log for one session from
ClickHouse. Filters (limit / after / before / level / search)
match the shared `LogEntryMixin` helper used by hog_function +
hog_flow.
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

export const getAgentApplicationsSetEnvCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agent_applications/${id}/set_env/`
}

/**
 * Replace the agent's encrypted env block.

The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
text gets stored on AgentApplication.encrypted_env; the worker
decrypts it at session start via the same Fernet schedule (see
agent-shared/src/runtime/encryption.ts).
 */
export const agentApplicationsSetEnvCreate = async (
    projectId: string,
    id: string,
    setEnvRequestApi: SetEnvRequestApi,
    options?: RequestInit
): Promise<AgentApplicationApi> => {
    return apiMutator<AgentApplicationApi>(getAgentApplicationsSetEnvCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setEnvRequestApi),
    })
}

export const getAgentApplicationsStatsUrl = (projectId: string, id: string, params?: AgentApplicationsStatsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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

export const getAgentCustomToolTemplatesListUrl = (projectId: string, params?: AgentCustomToolTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_custom_tool_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_custom_tool_templates/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary List the latest version of every custom tool template visible to the team.
 */
export const agentCustomToolTemplatesList = async (
    projectId: string,
    params?: AgentCustomToolTemplatesListParams,
    options?: RequestInit
): Promise<CustomToolTemplateSummaryApi[]> => {
    return apiMutator<CustomToolTemplateSummaryApi[]>(getAgentCustomToolTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentCustomToolTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_custom_tool_templates/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Create a new custom tool template — produces v1.
 */
export const agentCustomToolTemplatesCreate = async (
    projectId: string,
    customToolTemplateCreateApi: CustomToolTemplateCreateApi,
    options?: RequestInit
): Promise<CustomToolTemplateDetailApi> => {
    return apiMutator<CustomToolTemplateDetailApi>(getAgentCustomToolTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customToolTemplateCreateApi),
    })
}

export const getAgentCustomToolTemplatesNameRetrieveUrl = (
    projectId: string,
    name: string,
    params?: AgentCustomToolTemplatesNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Retrieve a custom tool template's latest version, or a specific version with `?version=N`.
 */
export const agentCustomToolTemplatesNameRetrieve = async (
    projectId: string,
    name: string,
    params?: AgentCustomToolTemplatesNameRetrieveParams,
    options?: RequestInit
): Promise<CustomToolTemplateDetailApi> => {
    return apiMutator<CustomToolTemplateDetailApi>(
        getAgentCustomToolTemplatesNameRetrieveUrl(projectId, name, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentCustomToolTemplatesNameArchiveCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/archive/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Soft-delete all versions of a custom tool template.
 */
export const agentCustomToolTemplatesNameArchiveCreate = async (
    projectId: string,
    name: string,
    customToolTemplateDetailApi: NonReadonly<CustomToolTemplateDetailApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentCustomToolTemplatesNameArchiveCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customToolTemplateDetailApi),
    })
}

export const getAgentCustomToolTemplatesNameDuplicateCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/duplicate/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Duplicate a custom tool template under a new name.
 */
export const agentCustomToolTemplatesNameDuplicateCreate = async (
    projectId: string,
    name: string,
    customToolTemplateDuplicateApi: CustomToolTemplateDuplicateApi,
    options?: RequestInit
): Promise<CustomToolTemplateDetailApi> => {
    return apiMutator<CustomToolTemplateDetailApi>(getAgentCustomToolTemplatesNameDuplicateCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customToolTemplateDuplicateApi),
    })
}

export const getAgentCustomToolTemplatesNamePublishCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/publish/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Publish a new version of the named custom tool template.
 */
export const agentCustomToolTemplatesNamePublishCreate = async (
    projectId: string,
    name: string,
    customToolTemplatePublishApi?: CustomToolTemplatePublishApi,
    options?: RequestInit
): Promise<CustomToolTemplateDetailApi> => {
    return apiMutator<CustomToolTemplateDetailApi>(getAgentCustomToolTemplatesNamePublishCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customToolTemplatePublishApi),
    })
}

export const getAgentCustomToolTemplatesNameUsagesListUrl = (
    projectId: string,
    name: string,
    params?: AgentCustomToolTemplatesNameUsagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/usages/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/usages/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary List the frozen agent revisions pinning this custom tool template.
 */
export const agentCustomToolTemplatesNameUsagesList = async (
    projectId: string,
    name: string,
    params?: AgentCustomToolTemplatesNameUsagesListParams,
    options?: RequestInit
): Promise<CustomToolTemplateUsageApi[]> => {
    return apiMutator<CustomToolTemplateUsageApi[]>(
        getAgentCustomToolTemplatesNameUsagesListUrl(projectId, name, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAgentCustomToolTemplatesNameVersionsListUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_custom_tool_templates/name/${name}/versions/`
}

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary List every version of the named custom tool template, newest first.
 */
export const agentCustomToolTemplatesNameVersionsList = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<TemplateVersionEntryApi[]> => {
    return apiMutator<TemplateVersionEntryApi[]>(getAgentCustomToolTemplatesNameVersionsListUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

export const getAgentFleetLiveSessionsUrl = (projectId: string, params?: AgentFleetLiveSessionsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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

export const getAgentSkillTemplatesListUrl = (projectId: string, params?: AgentSkillTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_skill_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_skill_templates/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary List the latest version of every skill template visible to the team.
 */
export const agentSkillTemplatesList = async (
    projectId: string,
    params?: AgentSkillTemplatesListParams,
    options?: RequestInit
): Promise<SkillTemplateSummaryApi[]> => {
    return apiMutator<SkillTemplateSummaryApi[]>(getAgentSkillTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentSkillTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Create a new skill template — produces v1.
 */
export const agentSkillTemplatesCreate = async (
    projectId: string,
    skillTemplateCreateApi: SkillTemplateCreateApi,
    options?: RequestInit
): Promise<SkillTemplateDetailApi> => {
    return apiMutator<SkillTemplateDetailApi>(getAgentSkillTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(skillTemplateCreateApi),
    })
}

export const getAgentSkillTemplatesNameRetrieveUrl = (
    projectId: string,
    name: string,
    params?: AgentSkillTemplatesNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_skill_templates/name/${name}/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_skill_templates/name/${name}/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Retrieve a skill template's latest version, or a specific version with `?version=N`.
 */
export const agentSkillTemplatesNameRetrieve = async (
    projectId: string,
    name: string,
    params?: AgentSkillTemplatesNameRetrieveParams,
    options?: RequestInit
): Promise<SkillTemplateDetailApi> => {
    return apiMutator<SkillTemplateDetailApi>(getAgentSkillTemplatesNameRetrieveUrl(projectId, name, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentSkillTemplatesNameArchiveCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/archive/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Soft-delete all versions of a template.
 */
export const agentSkillTemplatesNameArchiveCreate = async (
    projectId: string,
    name: string,
    skillTemplateDetailApi: NonReadonly<SkillTemplateDetailApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentSkillTemplatesNameArchiveCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(skillTemplateDetailApi),
    })
}

export const getAgentSkillTemplatesNameDuplicateCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/duplicate/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Duplicate a template under a new name (clones the latest version's content + files).
 */
export const agentSkillTemplatesNameDuplicateCreate = async (
    projectId: string,
    name: string,
    skillTemplateDuplicateApi: SkillTemplateDuplicateApi,
    options?: RequestInit
): Promise<SkillTemplateDetailApi> => {
    return apiMutator<SkillTemplateDetailApi>(getAgentSkillTemplatesNameDuplicateCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(skillTemplateDuplicateApi),
    })
}

export const getAgentSkillTemplatesNameFilesCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/files/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Add a companion file to the latest version of the template.
 */
export const agentSkillTemplatesNameFilesCreate = async (
    projectId: string,
    name: string,
    skillTemplateFileWriteApi: SkillTemplateFileWriteApi,
    options?: RequestInit
): Promise<SkillTemplateFileApi> => {
    return apiMutator<SkillTemplateFileApi>(getAgentSkillTemplatesNameFilesCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(skillTemplateFileWriteApi),
    })
}

export const getAgentSkillTemplatesNameFilesRenameCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/files-rename/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Rename a companion file inside the latest version of the template.
 */
export const agentSkillTemplatesNameFilesRenameCreate = async (
    projectId: string,
    name: string,
    skillTemplateFileRenameApi: SkillTemplateFileRenameApi,
    options?: RequestInit
): Promise<SkillTemplateFileApi> => {
    return apiMutator<SkillTemplateFileApi>(getAgentSkillTemplatesNameFilesRenameCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(skillTemplateFileRenameApi),
    })
}

export const getAgentSkillTemplatesNameFilesDestroyUrl = (projectId: string, name: string, filePath: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/files/${filePath}/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Remove a companion file from the latest version of the template.
 */
export const agentSkillTemplatesNameFilesDestroy = async (
    projectId: string,
    name: string,
    filePath: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAgentSkillTemplatesNameFilesDestroyUrl(projectId, name, filePath), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentSkillTemplatesNamePublishCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/publish/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Publish a new version of the named template.
 */
export const agentSkillTemplatesNamePublishCreate = async (
    projectId: string,
    name: string,
    skillTemplatePublishApi?: SkillTemplatePublishApi,
    options?: RequestInit
): Promise<SkillTemplateDetailApi> => {
    return apiMutator<SkillTemplateDetailApi>(getAgentSkillTemplatesNamePublishCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(skillTemplatePublishApi),
    })
}

export const getAgentSkillTemplatesNameUsagesListUrl = (
    projectId: string,
    name: string,
    params?: AgentSkillTemplatesNameUsagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_skill_templates/name/${name}/usages/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_skill_templates/name/${name}/usages/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary List the frozen agent revisions pinning this template (any version, or filtered by `pinned_version`).
 */
export const agentSkillTemplatesNameUsagesList = async (
    projectId: string,
    name: string,
    params?: AgentSkillTemplatesNameUsagesListParams,
    options?: RequestInit
): Promise<SkillTemplateUsageApi[]> => {
    return apiMutator<SkillTemplateUsageApi[]>(getAgentSkillTemplatesNameUsagesListUrl(projectId, name, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentSkillTemplatesNameVersionsListUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/agent_skill_templates/name/${name}/versions/`
}

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary List every version of the named template, newest first.
 */
export const agentSkillTemplatesNameVersionsList = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<TemplateVersionEntryApi[]> => {
    return apiMutator<TemplateVersionEntryApi[]>(getAgentSkillTemplatesNameVersionsListUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}
