/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface AgentApplicationApi {
    readonly id: string
    readonly team: number
    /** @maxLength 255 */
    name: string
    /** @maxLength 63 */
    slug: string
    description?: string
    /** @nullable */
    readonly live_revision: string | null
    archived?: boolean
    /** @nullable */
    readonly archived_at: string | null
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedAgentApplicationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgentApplicationApi[]
}

/**
 * * `draft` - draft
 * `ready` - ready
 * `live` - live
 * `archived` - archived
 */
export type AgentRevisionStateEnumApi = (typeof AgentRevisionStateEnumApi)[keyof typeof AgentRevisionStateEnumApi]

export const AgentRevisionStateEnumApi = {
    Draft: 'draft',
    Ready: 'ready',
    Live: 'live',
    Archived: 'archived',
} as const

export interface AgentRevisionApi {
    readonly id: string
    readonly application: string
    /** @nullable */
    parent_revision?: string | null
    readonly state: AgentRevisionStateEnumApi
    bundle_uri?: string
    /** @nullable */
    readonly bundle_sha256: string | null
    spec?: unknown
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedAgentRevisionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgentRevisionApi[]
}

export interface PatchedAgentRevisionApi {
    readonly id?: string
    readonly application?: string
    /** @nullable */
    parent_revision?: string | null
    readonly state?: AgentRevisionStateEnumApi
    bundle_uri?: string
    /** @nullable */
    readonly bundle_sha256?: string | null
    spec?: unknown
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
    readonly updated_at?: string
}

export type WriteBundleRequestApiFiles = { [key: string]: string }

/**
 * * `replace` - replace
 * `merge` - merge
 */
export type WriteBundleRequestModeEnumApi =
    (typeof WriteBundleRequestModeEnumApi)[keyof typeof WriteBundleRequestModeEnumApi]

export const WriteBundleRequestModeEnumApi = {
    Replace: 'replace',
    Merge: 'merge',
} as const

/**
 * Body shape for PUT /revisions/<id>/bundle/ — the bulk upload.

`files` is a `{path: utf-8 content}` map. `mode='replace'` wipes the
existing bundle before writing the new set; `'merge'` upserts.
 */
export interface WriteBundleRequestApi {
    files: WriteBundleRequestApiFiles
    mode?: WriteBundleRequestModeEnumApi
}

/**
 * Body shape for POST /revisions/<id>/clone_from/ — copy every file
from `source_revision_id` into this (draft) revision.
 */
export interface CloneFromRequestApi {
    source_revision_id: string
}

/**
 * Body shape for PUT /revisions/<id>/file/. `path` lives in the query
string (matches the janitor wire format); `content` is the new file body.
 */
export interface WriteFileRequestApi {
    content: string
}

export interface AgentRevisionValidationErrorApi {
    code: string
    message: string
    pointer: string
}

export interface AgentRevisionValidateResponseApi {
    ok: boolean
    revision_id: string
    revision_state: string
    errors: AgentRevisionValidationErrorApi[]
    resolved_natives: string[]
}

/**
 * Body shape for POST /revisions/clone_from/ — atomically create a new
draft revision under `application_id` and clone its initial bundle from
`source_revision_id`. Convenience for the "edit live" flow so the MCP
doesn't have to do create-then-clone-from in two calls.
 */
export interface NewDraftRevisionRequestApi {
    application_id: string
    source_revision_id: string
}

export interface PatchedAgentApplicationApi {
    readonly id?: string
    readonly team?: number
    /** @maxLength 255 */
    name?: string
    /** @maxLength 63 */
    slug?: string
    description?: string
    /** @nullable */
    readonly live_revision?: string | null
    archived?: boolean
    /** @nullable */
    readonly archived_at?: string | null
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
    readonly updated_at?: string
}

export interface AgentSessionUsageTotalApi {
    tokens_in: number
    tokens_out: number
    cost_input: number
    cost_output: number
    cost_total: number
}

/**
 * @nullable
 */
export type AgentSessionSummaryApiPrincipal = { [key: string]: unknown } | null

export interface AgentSessionSummaryApi {
    id: string
    application_id: string
    revision_id: string
    state: string
    /** @nullable */
    external_key: string | null
    /** @nullable */
    principal: AgentSessionSummaryApiPrincipal
    turns: number
    /** @nullable */
    preview: string | null
    usage_total: AgentSessionUsageTotalApi
    retry_count: number
    created_at: string
    updated_at: string
}

export interface AgentApplicationSessionsListResponseApi {
    sessions: AgentSessionSummaryApi[]
}

export type SetEnvRequestApiEnv = { [key: string]: string }

/**
 * Body shape for AgentApplicationViewSet.set_env.

`env` is a JSON object of string→string. The view encrypts it via the
same Fernet schedule the worker uses to decrypt.
 */
export interface SetEnvRequestApi {
    env: SetEnvRequestApiEnv
}

export type AgentNativeToolEntryApiSchema = { [key: string]: unknown }

export interface AgentNativeToolEntryApi {
    id: string
    schema: AgentNativeToolEntryApiSchema
}

export interface AgentNativeToolsListResponseApi {
    tools: AgentNativeToolEntryApi[]
}

export type AgentApplicationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AgentApplicationsRevisionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AgentApplicationsRevisionsFileRetrieveParams = {
    /**
     * Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.
     */
    path: string
}

export type AgentApplicationsRevisionsFileUpdateParams = {
    /**
     * Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.
     */
    path: string
}

export type AgentApplicationsRevisionsFileDestroyParams = {
    /**
     * Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.
     */
    path: string
}

export type AgentApplicationsSessionsListParams = {
    /**
     * ISO datetime — return sessions with created_at >= this.
     */
    created_after?: string
    /**
     * ISO datetime — return sessions with created_at <= this.
     */
    created_before?: string
    limit?: number
    offset?: number
    /**
     * Only return sessions started against this specific revision.
     */
    revision_id?: string
    /**
     * Filter by session state. Comma-separated list accepted (e.g. `completed,failed`). Valid values: queued, running, waiting, completed, failed.
     */
    state?: string
}

export type AgentApplicationsSessionsRetrieveParams = {
    /**
     * If set, return only the most recent N messages from the conversation. `usage_total` is still computed over the full session — only the transcript is trimmed. The response includes `conversation_trimmed: true` and `conversation_total_turns` so the caller knows how much was hidden.
     */
    last_n?: number
}
