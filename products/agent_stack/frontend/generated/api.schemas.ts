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
