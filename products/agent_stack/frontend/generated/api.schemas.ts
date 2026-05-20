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
    /**
     * Human-readable display name for the application.
     * @maxLength 255
     */
    name: string
    /**
     * Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.
     * @maxLength 63
     * @pattern ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$
     */
    slug: string
    /** Optional free-text description shown in the management UI. */
    description?: string
    /** True if an encrypted env is set. Plaintext is never returned. */
    readonly has_env: boolean
    /** The application's `.env` rendered as text with every value replaced by asterisks (`KEY=********`). Suitable for showing in a textarea so the user can confirm which keys are set. Empty string when no env is configured. */
    readonly env_redacted: string
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
 * * `pending_upload` - pending_upload
 * `uploaded` - uploaded
 * `validating` - validating
 * `ready` - ready
 * `failed` - failed
 */
export type AgentApplicationRevisionStateEnumApi =
    (typeof AgentApplicationRevisionStateEnumApi)[keyof typeof AgentApplicationRevisionStateEnumApi]

export const AgentApplicationRevisionStateEnumApi = {
    PendingUpload: 'pending_upload',
    Uploaded: 'uploaded',
    Validating: 'validating',
    Ready: 'ready',
    Failed: 'failed',
} as const

/**
 * * `live` - live
 * `preview` - preview
 * `disabled` - disabled
 */
export type DeploymentStatusEnumApi = (typeof DeploymentStatusEnumApi)[keyof typeof DeploymentStatusEnumApi]

export const DeploymentStatusEnumApi = {
    Live: 'live',
    Preview: 'preview',
    Disabled: 'disabled',
} as const

export interface AgentApplicationRevisionApi {
    readonly id: string
    readonly team: number
    readonly application: string
    readonly state: AgentApplicationRevisionStateEnumApi
    readonly deployment_status: DeploymentStatusEnumApi
    /** @nullable */
    readonly bundle_size: number | null
    readonly bundle_sha256: string
    readonly top_level_config: unknown
    readonly parsed_manifest: unknown
    readonly validation_report: unknown
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedAgentApplicationRevisionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgentApplicationRevisionApi[]
}

export interface PatchedAgentApplicationApi {
    readonly id?: string
    readonly team?: number
    /**
     * Human-readable display name for the application.
     * @maxLength 255
     */
    name?: string
    /**
     * Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.
     * @maxLength 63
     * @pattern ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$
     */
    slug?: string
    /** Optional free-text description shown in the management UI. */
    description?: string
    /** True if an encrypted env is set. Plaintext is never returned. */
    readonly has_env?: boolean
    /** The application's `.env` rendered as text with every value replaced by asterisks (`KEY=********`). Suitable for showing in a textarea so the user can confirm which keys are set. Empty string when no env is configured. */
    readonly env_redacted?: string
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
    readonly updated_at?: string
}

export interface CompleteUploadRequestApi {
    /** ID of the revision returned from start_deploy whose bundle has been uploaded. */
    revision_id: string
}

export interface DisableRevisionRequestApi {
    /** ID of the revision to set deployment_status=disabled. Allowed from any state — use this to take a broken live or preview revision out of traffic. */
    revision_id: string
}

export interface PreviewRevisionRequestApi {
    /** ID of the revision to mark as preview. Must be state=ready. Multiple preview revisions can coexist; no siblings are demoted. */
    revision_id: string
}

export interface PromoteRevisionRequestApi {
    /** ID of the revision to promote. Must be state=ready. Any prior live revision on this application is atomically demoted to deployment_status=disabled. */
    revision_id: string
}

export interface StartDeployRequestApi {
    /**
     * SHA-256 of the bundle the CLI is about to upload, lowercase hex (64 chars).
     * @pattern ^[0-9a-f]{64}$
     */
    bundle_sha256: string
    /**
     * Bundle size in bytes. The presigned upload is bound to this exact size.
     * @minimum 1
     */
    bundle_size: number
    /** Parsed contents of `.ass.yaml`. Validated synchronously at deploy start; bundle-level checks are deferred to the async validator when it lands. */
    top_level_config: unknown
}

/**
 * Form fields the CLI must include in the multipart POST.
 */
export type StartDeployResponseApiUploadFields = { [key: string]: string }

export interface StartDeployResponseApi {
    /** The newly-created revision in state=pending_upload. */
    revision_id: string
    /** Presigned S3 POST URL the CLI uploads the bundle to. */
    upload_url: string
    /** Form fields the CLI must include in the multipart POST. */
    upload_fields: StartDeployResponseApiUploadFields
    /** When the presigned URL stops being valid. */
    expires_at: string
    /** Exact size in bytes the upload must be. */
    max_size: number
    /** SHA-256 the uploaded bundle must hash to. */
    required_sha256: string
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
     * * `live` - live
     * `preview` - preview
     * `disabled` - disabled
     */
    deployment_status?: AgentApplicationsRevisionsListDeploymentStatus
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * * `pending_upload` - pending_upload
     * `uploaded` - uploaded
     * `validating` - validating
     * `ready` - ready
     * `failed` - failed
     */
    state?: AgentApplicationsRevisionsListState
}

export type AgentApplicationsRevisionsListDeploymentStatus =
    (typeof AgentApplicationsRevisionsListDeploymentStatus)[keyof typeof AgentApplicationsRevisionsListDeploymentStatus]

export const AgentApplicationsRevisionsListDeploymentStatus = {
    Disabled: 'disabled',
    Live: 'live',
    Preview: 'preview',
} as const

export type AgentApplicationsRevisionsListState =
    (typeof AgentApplicationsRevisionsListState)[keyof typeof AgentApplicationsRevisionsListState]

export const AgentApplicationsRevisionsListState = {
    Failed: 'failed',
    PendingUpload: 'pending_upload',
    Ready: 'ready',
    Uploaded: 'uploaded',
    Validating: 'validating',
} as const

export type AgentApplicationsSessionsList200 = { [key: string]: unknown }

export type AgentApplicationsSessionsRetrieve200 = { [key: string]: unknown }

export type AgentApplicationsSessionsCancel200 = { [key: string]: unknown }

export type AgentApplicationsSessionsLogs200 = { [key: string]: unknown }
