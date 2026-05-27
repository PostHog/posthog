/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface DeploymentProjectApi {
    /** Unique identifier for the deployment project. */
    readonly id: string
    /**
     * Human-readable project name shown in the UI.
     * @maxLength 200
     */
    name: string
    /**
     * URL-safe handle. Combined with the team id to form the Cloudflare project name; the actual subdomain comes from Cloudflare and is returned in the read-only `subdomain` field. Must be unique per team.
     * @maxLength 80
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /**
     * HTTPS URL of the connected GitHub repository, resolved from the selected repository id.
     * @maxLength 1024
     */
    readonly repo_url: string
    /**
     * Branch PostHog tracks for deployment updates. Defaults to the repository default branch.
     * @maxLength 255
     */
    default_branch?: string
    /**
     * Existing PostHog GitHub integration id used for repository access.
     * @nullable
     */
    github_integration_id?: number | null
    /**
     * Stable GitHub repository identifier selected from the existing integration's repository list.
     * @nullable
     */
    github_repo_id?: number | null
    /**
     * Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).
     * @nullable
     */
    build_command?: string | null
    /**
     * Directory containing the built static site, relative to the repository root.
     * @maxLength 255
     */
    output_dir?: string
    /**
     * Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.
     * @maxLength 50
     * @nullable
     */
    framework?: string | null
    /** If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them. */
    inject_posthog_snippet?: boolean
    /** Cloudflare Pages project name, assigned during provisioning. */
    readonly cloudflare_project_name: string
    /** Public subdomain at which deployments of this project serve. */
    readonly subdomain: string
    /**
     * Timestamp when the Cloudflare project was fully provisioned and ready to receive deploys.
     * @nullable
     */
    readonly cloudflare_ready_at: string | null
    /**
     * The deployment currently serving traffic for this project. Null if no deployment has ever succeeded.
     * @nullable
     */
    readonly current_deployment: string | null
    /** True when the project has both a provisioned Cloudflare backend and a configured GitHub credential — meaning a deploy can be triggered right now. */
    readonly is_ready_to_deploy: boolean
    /** Timestamp when the project was created. */
    readonly created_at: string
    /** Timestamp when the project was last modified. */
    readonly updated_at: string
}

export interface PaginatedDeploymentProjectListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DeploymentProjectApi[]
}

export interface DeploymentProjectCreateApi {
    /**
     * Human-readable project name shown in the UI.
     * @maxLength 200
     */
    name: string
    /**
     * URL-safe handle. Becomes the subdomain `{slug}.posthog-app.com`. Must be unique per team.
     * @maxLength 80
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /**
     * Branch PostHog tracks for deployment updates. Defaults to the repository default branch.
     * @maxLength 255
     */
    default_branch?: string
    /** Existing PostHog GitHub integration id used for repository access. */
    github_integration_id: number
    /** Stable GitHub repository identifier selected from the existing integration's repository list. */
    github_repo_id: number
    /**
     * Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).
     * @nullable
     */
    build_command?: string | null
    /**
     * Directory containing the built static site, relative to the repository root.
     * @maxLength 255
     */
    output_dir?: string
    /**
     * Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.
     * @maxLength 50
     * @nullable
     */
    framework?: string | null
    /** If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them. */
    inject_posthog_snippet?: boolean
}

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

/**
 * * `manual` - Manual
 * `git` - Git
 * `redeploy` - Redeploy
 * `rollback` - Rollback
 * `seed` - Seed
 */
export type TriggerKindEnumApi = (typeof TriggerKindEnumApi)[keyof typeof TriggerKindEnumApi]

export const TriggerKindEnumApi = {
    Manual: 'manual',
    Git: 'git',
    Redeploy: 'redeploy',
    Rollback: 'rollback',
    Seed: 'seed',
} as const

/**
 * * `dispatch` - Dispatch
 * `clone` - Clone
 * `install` - Install
 * `build` - Build
 * `publish` - Publish
 */
export type ErrorStepEnumApi = (typeof ErrorStepEnumApi)[keyof typeof ErrorStepEnumApi]

export const ErrorStepEnumApi = {
    Dispatch: 'dispatch',
    Clone: 'clone',
    Install: 'install',
    Build: 'build',
    Publish: 'publish',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export const DeploymentApiErrorStep = { ...ErrorStepEnumApi, ...BlankEnumApi } as const
export interface DeploymentApi {
    /** Unique identifier for the deployment. */
    readonly id: string
    /** The deployment project this deployment belongs to. */
    readonly project: string
    /** Current pipeline stage. Valid values: queued, initializing, building, ready, error, cancelled.

  * `queued` - Queued
  * `initializing` - Initializing
  * `building` - Building
  * `ready` - Ready
  * `error` - Error
  * `cancelled` - Cancelled */
    status: DeploymentStatusEnumApi
    /**
     * When the pipeline started building. Null while still queued.
     * @nullable
     */
    started_at?: string | null
    /**
     * When the pipeline finished (regardless of outcome). Null while still running.
     * @nullable
     */
    finished_at?: string | null
    /** When the deployment row was created (~ queued_at). */
    readonly created_at: string
    /**
     * Git commit SHA the deployment was built from.
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
     * Email address of the commit author. Used by the Author filter on the list page.
     * @maxLength 255
     */
    commit_author_email?: string
    /**
     * HTTPS URL of the source repository. Captured at deploy time.
     * @maxLength 1024
     */
    repo_url?: string
    /**
     * Source branch the deployment was built from.
     * @maxLength 255
     */
    branch?: string
    /**
     * Public URL serving the built site once ready.
     * @maxLength 1024
     */
    deployment_url?: string
    /**
     * URL of the captured site screenshot, used in the list/card view.
     * @maxLength 1024
     */
    preview_image_url?: string
    /**
     * The deployment this one was triggered from (for rollbacks and redeploys).
     * @nullable
     */
    readonly triggered_by_deployment: string | null
    /**
     * Posthog user id of the user who clicked Deploy/Redeploy/Rollback. Null for git-triggered or seed rows.
     * @nullable
     */
    readonly triggered_by_user_id: number | null
    /** What caused this deployment to start: manual | git | redeploy | rollback | seed.

  * `manual` - Manual
  * `git` - Git
  * `redeploy` - Redeploy
  * `rollback` - Rollback
  * `seed` - Seed */
    trigger_kind: TriggerKindEnumApi
    /** Failure detail set when status=error. Empty for successful or in-flight deployments. */
    readonly error_message: string
    /** Build step that failed: dispatch | clone | install | build | publish. Empty when status != error.

  * `dispatch` - Dispatch
  * `clone` - Clone
  * `install` - Install
  * `build` - Build
  * `publish` - Publish */
    error_step?: (typeof DeploymentApiErrorStep)[keyof typeof DeploymentApiErrorStep]
    /** Cloudflare Pages deployment id, set once the publish step succeeds. */
    readonly cloudflare_deployment_id: string
    /** Temporal workflow id for this build. Used for cancellation signalling. */
    readonly temporal_workflow_id: string
    /** True if this deployment is currently serving production traffic for its project. */
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
 * Body of POST /api/projects/{}/deployment_projects/{}/deployments/.
 */
export interface DeploymentCreateInputApi {
    /**
     * Optional commit SHA. If omitted, the build worker resolves HEAD of `branch` (or the project's default_branch).
     * @maxLength 64
     */
    commit_sha?: string
    /**
     * Optional branch override. If omitted, uses the project's `default_branch`.
     * @maxLength 255
     */
    branch?: string
}

/**
 * Response shape returned with HTTP 409 when an active deploy exists.
 */
export interface DeploymentConflictResponseApi {
    /** Reason for the conflict. */
    detail: string
    /** The deployment currently in-flight for the project. Frontend can poll this id. */
    active_deployment_id: string
}

/**
 * Response shape for one-off action endpoints (cancel, refresh_preview).
 */
export interface DeploymentActionResponseApi {
    /** Short human-readable confirmation message. */
    detail: string
}

export interface DeploymentEventApi {
    /** Unique identifier for the event row. */
    readonly id: string
    /** The deployment this event belongs to. */
    readonly deployment: string
    /**
     * Event category, e.g. `status_changed`, `preview_captured`, `dispatched`.
     * @maxLength 50
     */
    event_type: string
    /** Arbitrary structured payload for the event. Shape varies by event_type. */
    payload: unknown
    /** When the event occurred (server time). */
    readonly occurred_at: string
}

export interface PaginatedDeploymentEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DeploymentEventApi[]
}

/**
 * One line of build output emitted by the build worker as a `$log` event.
 */
export interface DeploymentLogEntryApi {
    /** When the line was emitted by the build worker. */
    timestamp: string
    /**
     * Log level: "info" | "warn" | "error". Null if the event did not carry one.
     * @nullable
     */
    level: string | null
    /**
     * Pipeline step: "clone" | "install" | "build" | "publish". Null if the event did not carry one.
     * @nullable
     */
    step: string | null
    /**
     * The log line itself (a single line of stdout or stderr).
     * @nullable
     */
    line: string | null
    /**
     * Set on the last line of a step; null on all other lines.
     * @nullable
     */
    exit_code: number | null
}

/**
 * Response shape for GET /deployments/{id}/logs/.
 */
export interface DeploymentLogsResponseApi {
    /** Log lines for the deployment, oldest first. */
    results: DeploymentLogEntryApi[]
    /** True if the row limit was hit and older lines may exist beyond this page. */
    has_more: boolean
    /** The hard cap applied by the server. */
    row_limit: number
}

export interface DeploymentProjectWriteApi {
    /**
     * Human-readable project name shown in the UI.
     * @maxLength 200
     */
    name: string
    /**
     * URL-safe handle. Combined with the team id to form the Cloudflare project name; the actual subdomain comes from Cloudflare and is returned in the read-only `subdomain` field. Must be unique per team.
     * @maxLength 80
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /**
     * Branch PostHog tracks for deployment updates. Defaults to the repository default branch.
     * @maxLength 255
     */
    default_branch?: string
    /**
     * Existing PostHog GitHub integration id used for repository access.
     * @nullable
     */
    github_integration_id?: number | null
    /**
     * Stable GitHub repository identifier selected from the existing integration's repository list.
     * @nullable
     */
    github_repo_id?: number | null
    /**
     * Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).
     * @nullable
     */
    build_command?: string | null
    /**
     * Directory containing the built static site, relative to the repository root.
     * @maxLength 255
     */
    output_dir?: string
    /**
     * Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.
     * @maxLength 50
     * @nullable
     */
    framework?: string | null
    /** If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them. */
    inject_posthog_snippet?: boolean
}

export interface PatchedDeploymentProjectWriteApi {
    /**
     * Human-readable project name shown in the UI.
     * @maxLength 200
     */
    name?: string
    /**
     * URL-safe handle. Combined with the team id to form the Cloudflare project name; the actual subdomain comes from Cloudflare and is returned in the read-only `subdomain` field. Must be unique per team.
     * @maxLength 80
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug?: string
    /**
     * Branch PostHog tracks for deployment updates. Defaults to the repository default branch.
     * @maxLength 255
     */
    default_branch?: string
    /**
     * Existing PostHog GitHub integration id used for repository access.
     * @nullable
     */
    github_integration_id?: number | null
    /**
     * Stable GitHub repository identifier selected from the existing integration's repository list.
     * @nullable
     */
    github_repo_id?: number | null
    /**
     * Optional shell command run inside the build container. Null = the build worker infers it from `framework` (or auto-detection if framework is also null).
     * @nullable
     */
    build_command?: string | null
    /**
     * Directory containing the built static site, relative to the repository root.
     * @maxLength 255
     */
    output_dir?: string
    /**
     * Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.
     * @maxLength 50
     * @nullable
     */
    framework?: string | null
    /** If true, the build injects a PostHog snippet into every HTML file that registers `release = deployment_id` as a super-property — runtime exceptions are then linked back to the deployment that introduced them. */
    inject_posthog_snippet?: boolean
}

/**
 * Response shape for refreshing a deployment project's GitHub branch.
 */
export interface DeploymentProjectRefreshResponseApi {
    /** Human-readable explanation of the refresh result. */
    detail: string
    /** HTTPS URL of the connected GitHub repository. */
    repo_url: string
    /** Branch checked by the refresh action. */
    default_branch: string
    /** Current GitHub HEAD SHA for default_branch. */
    commit_sha: string
}

/**
 * Inputs the `/detect/` endpoint needs to suggest a project config.

Decouples detection from any one git provider — callers fetch
`package.json` and the list of lockfiles however they like (GitHub
raw content via the team's existing integration, a temporary clone,
user-pasted JSON during early development) and pass them here.
 */
export interface DetectConfigRequestApi {
    /** Parsed contents of the repo's `package.json`. Pass null or omit if the repo doesn't have one — the response is then the plain-HTML fallback. */
    package_json?: unknown
    /** Filenames of package-manager lockfiles found in the repo root (e.g. ["pnpm-lock.yaml"]). Used to pick the package manager. */
    lockfiles?: string[]
}

/**
 * * `npm` - npm
 * `pnpm` - pnpm
 * `yarn` - yarn
 * `bun` - bun
 */
export type PackageManagerEnumApi = (typeof PackageManagerEnumApi)[keyof typeof PackageManagerEnumApi]

export const PackageManagerEnumApi = {
    Npm: 'npm',
    Pnpm: 'pnpm',
    Yarn: 'yarn',
    Bun: 'bun',
} as const

/**
 * Suggested project config. Every field is overridable in the connect-repo UI.

`build_command`, `output_dir`, and `framework` map directly to the
`DeploymentProject` model fields. `package_manager`, `install_command`,
and `node_version` are informational hints — the model doesn't store
them today, but the UI can display them so the user knows what the
build worker will end up running.
 */
export interface DetectConfigResponseApi {
    /** Detected package manager from lockfile presence.

  * `npm` - npm
  * `pnpm` - pnpm
  * `yarn` - yarn
  * `bun` - bun */
    package_manager: PackageManagerEnumApi
    /** Suggested install command, or empty when no install is needed. */
    install_command: string
    /** Suggested build command, or empty when no known framework matched. */
    build_command: string
    /** Suggested output directory relative to repo root. */
    output_dir: string
    /** Suggested Node major version, parsed from `engines.node` or defaulted to 20. */
    node_version: string
    /**
     * Detected framework hint (e.g. `nextjs`, `vite`, `astro`) to write into `DeploymentProject.framework`. Null when no framework matched — leaving the field null lets the build worker fall back to its own auto-detection.
     * @nullable
     */
    framework: string | null
}

export type DeploymentProjectsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
    /**
     * A search term.
     */
    search?: string
}

export type DeploymentProjectsDeploymentsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
    /**
     * A search term.
     */
    search?: string
}

export type DeploymentProjectsDeploymentsEventsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
    /**
     * A search term.
     */
    search?: string
}
