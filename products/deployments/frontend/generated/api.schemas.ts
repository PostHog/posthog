/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `queued` - Queued
 * `initializing` - Initializing
 * `building` - Building
 * `ready` - Ready
 * `error` - Error
 * `cancelled` - Cancelled
 */
export type DeploymentStatusEnumApi = (typeof DeploymentStatusEnumApi)[keyof typeof DeploymentStatusEnumApi]

export const DeploymentStatusEnumApi = {
    Queued: 'queued',
    Initializing: 'initializing',
    Building: 'building',
    Ready: 'ready',
    Error: 'error',
    Cancelled: 'cancelled',
} as const

/**
 * * `git` - Git
 * `redeploy` - Redeploy
 * `rollback` - Rollback
 * `seed` - Seed
 */
export type TriggerKindEnumApi = (typeof TriggerKindEnumApi)[keyof typeof TriggerKindEnumApi]

export const TriggerKindEnumApi = {
    Git: 'git',
    Redeploy: 'redeploy',
    Rollback: 'rollback',
    Seed: 'seed',
} as const

export interface DeploymentApi {
    /** Unique identifier for the deployment. */
    readonly id: string
    /** Current pipeline stage for the deployment. Valid values: queued, initializing, building, ready, error, cancelled.

  * `queued` - Queued
  * `initializing` - Initializing
  * `building` - Building
  * `ready` - Ready
  * `error` - Error
  * `cancelled` - Cancelled */
    status: DeploymentStatusEnumApi
    /**
     * Timestamp when the pipeline started building. Null while still queued.
     * @nullable
     */
    started_at?: string | null
    /**
     * Timestamp when the pipeline finished (regardless of outcome). Null while still running.
     * @nullable
     */
    finished_at?: string | null
    /** Timestamp when the deployment row was created. */
    readonly created_at: string
    /**
     * Git commit SHA the deployment was built from. Empty for non-git triggers.
     * @maxLength 64
     */
    commit_sha?: string
    /** Commit message associated with the commit SHA. */
    commit_message?: string
    /**
     * Display name of the commit author.
     * @maxLength 255
     */
    commit_author_name?: string
    /**
     * Email address of the commit author.
     * @maxLength 255
     */
    commit_author_email?: string
    /**
     * HTTPS URL of the source repository this deployment came from.
     * @maxLength 1024
     */
    repo_url?: string
    /**
     * Source branch the deployment was built from.
     * @maxLength 255
     */
    branch?: string
    /**
     * Public URL where the built site is served once the deployment is ready.
     * @maxLength 1024
     */
    deployment_url?: string
    /**
     * URL of a screenshot capture of the deployed site, used in the list view.
     * @maxLength 1024
     */
    preview_image_url?: string
    /**
     * The deployment this one was triggered from (e.g. for rollbacks/redeploys).
     * @nullable
     */
    readonly triggered_by_deployment: string | null
    /** What caused this deployment to start. One of: git, redeploy, rollback, seed.

  * `git` - Git
  * `redeploy` - Redeploy
  * `rollback` - Rollback
  * `seed` - Seed */
    trigger_kind: TriggerKindEnumApi
    /** Whether this deployment is the team's currently-serving production deployment. */
    readonly is_current: boolean
    /** Build duration in seconds (finished_at - started_at). 0 while still running. */
    readonly duration_seconds: number
}

export interface PaginatedDeploymentListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DeploymentApi[]
}

/**
 * Response shape for the redeploy/rollback/refresh-preview stubs.
 */
export interface DeploymentActionResponseApi {
    /** Human-readable explanation of the stub response. */
    detail: string
}

export type DeploymentsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
