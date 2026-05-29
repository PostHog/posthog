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
    AgentApplicationApprovalsListResponseApi,
    AgentApplicationSessionLogsResponseApi,
    AgentApplicationSessionsListResponseApi,
    AgentApplicationSessionsRetrieveResponseApi,
    AgentApplicationsApprovalsListParams,
    AgentApplicationsListParams,
    AgentApplicationsPreviewProxyGetParams,
    AgentApplicationsPreviewProxyParams,
    AgentApplicationsRevisionsFileDestroyParams,
    AgentApplicationsRevisionsFileRetrieveParams,
    AgentApplicationsRevisionsFileUpdateParams,
    AgentApplicationsRevisionsListParams,
    AgentApplicationsSessionLogsParams,
    AgentApplicationsSessionsListParams,
    AgentApplicationsSessionsRetrieveParams,
    AgentApprovalsDecideResponseApi,
    AgentNativeToolsListResponseApi,
    AgentRevisionApi,
    AgentRevisionSystemPromptResponseApi,
    AgentRevisionValidateResponseApi,
    CloneFromRequestApi,
    DecideApprovalRequestApi,
    NewDraftRevisionRequestApi,
    PaginatedAgentApplicationListApi,
    PaginatedAgentRevisionListApi,
    PatchedAgentApplicationApi,
    PatchedAgentRevisionApi,
    SetEnvRequestApi,
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
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
The janitor computes the digest and updates the revision row in PG;
Django re-reads the row before returning so the response reflects
the persisted state.
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
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
