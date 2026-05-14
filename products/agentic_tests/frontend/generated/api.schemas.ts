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
 * * `running` - Running
 * `passed` - Passed
 * `failed` - Failed
 * `timeout` - Timeout
 * `error` - Error
 */
export type AgenticTestRunStatusEnumApi = (typeof AgenticTestRunStatusEnumApi)[keyof typeof AgenticTestRunStatusEnumApi]

export const AgenticTestRunStatusEnumApi = {
    Running: 'running',
    Passed: 'passed',
    Failed: 'failed',
    Timeout: 'timeout',
    Error: 'error',
} as const

/**
 * * `manual` - Manual
 * `scheduled` - Scheduled
 */
export type AgenticTestRunSourceEnumApi = (typeof AgenticTestRunSourceEnumApi)[keyof typeof AgenticTestRunSourceEnumApi]

export const AgenticTestRunSourceEnumApi = {
    Manual: 'manual',
    Scheduled: 'scheduled',
} as const

export interface AgenticTestRunApi {
    readonly id: string
    readonly agentic_test: string
    readonly started_at: string
    /** @nullable */
    readonly finished_at: string | null
    readonly status: AgenticTestRunStatusEnumApi
    /** What triggered this run. New sources may be added (e.g. webhook, api).

  * `manual` - Manual
  * `scheduled` - Scheduled */
    readonly source: AgenticTestRunSourceEnumApi
    /** @nullable */
    readonly duration_ms: number | null
    /** Raw response from the browser agent. */
    readonly output: unknown
    readonly error_message: string
    /** Runner-specific session id (e.g. browserbase) so we can deep-link back to the agent run. */
    readonly external_session_id: string
    readonly screenshot_url: string
    /** Browserbase region this run executed in (e.g. us-west-2). */
    readonly region: string
    /** PostHog session replay id recorded by posthog-js inside the browserbase session. */
    readonly posthog_session_id: string
    /** Append-only list of agent events emitted during the run (status, tool_call, tool_result, model_text, final). One dict per event. */
    readonly log_entries: unknown
}

export interface PaginatedAgenticTestRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgenticTestRunApi[]
}

/**
 * * `active` - Active
 * `paused` - Paused
 * `proposed` - Proposed
 * `rejected` - Rejected
 */
export type AgenticTestStatusEnumApi = (typeof AgenticTestStatusEnumApi)[keyof typeof AgenticTestStatusEnumApi]

export const AgenticTestStatusEnumApi = {
    Active: 'active',
    Paused: 'paused',
    Proposed: 'proposed',
    Rejected: 'rejected',
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface AgenticTestApi {
    readonly id: string
    /** @maxLength 255 */
    name: string
    description?: string
    /** @maxLength 2048 */
    target_url: string
    /** Natural-language instructions for the browser agent. */
    prompt: string
    status?: AgenticTestStatusEnumApi
    /** List of post-run checks the test must satisfy, scoped to the agent's own PostHog session. Each item: {type, ...config}. Supported types: event_captured, event_not_captured, no_console_errors. */
    assertions?: unknown
    /**
     * Cron expression (5 fields, UTC) describing the run cadence. Empty means manual-only — no automatic runs.
     * @maxLength 128
     */
    schedule_cron?: string
    /** List of Browserbase regions the test may run from. Each run picks one at random. Empty list means use the Browserbase default (us-west-2). Supported: us-west-2, us-east-1, eu-central-1, ap-southeast-1. */
    regions?: unknown
    /**
     * When the next scheduled run is due. Null when the test is not on a schedule.
     * @nullable
     */
    readonly next_run_at: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    source_replay_id?: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly last_run_at: string | null
    /** Most recent run for this test, or null if none have completed yet. */
    readonly last_run: AgenticTestRunApi | null
}

export interface PaginatedAgenticTestListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgenticTestApi[]
}

export interface PatchedAgenticTestApi {
    readonly id?: string
    /** @maxLength 255 */
    name?: string
    description?: string
    /** @maxLength 2048 */
    target_url?: string
    /** Natural-language instructions for the browser agent. */
    prompt?: string
    status?: AgenticTestStatusEnumApi
    /** List of post-run checks the test must satisfy, scoped to the agent's own PostHog session. Each item: {type, ...config}. Supported types: event_captured, event_not_captured, no_console_errors. */
    assertions?: unknown
    /**
     * Cron expression (5 fields, UTC) describing the run cadence. Empty means manual-only — no automatic runs.
     * @maxLength 128
     */
    schedule_cron?: string
    /** List of Browserbase regions the test may run from. Each run picks one at random. Empty list means use the Browserbase default (us-west-2). Supported: us-west-2, us-east-1, eu-central-1, ap-southeast-1. */
    regions?: unknown
    /**
     * When the next scheduled run is due. Null when the test is not on a schedule.
     * @nullable
     */
    readonly next_run_at?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    source_replay_id?: string | null
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    readonly last_run_at?: string | null
    /** Most recent run for this test, or null if none have completed yet. */
    readonly last_run?: AgenticTestRunApi | null
}

export interface DetectFlowsResponseApi {
    /** ID of the created task. */
    task_id: string
    /**
     * ID of the task run to stream logs from.
     * @nullable
     */
    task_run_id: string | null
    /**
     * Current status of the task run: queued, in_progress, completed, failed, or cancelled.
     * @nullable
     */
    status?: string | null
}

export interface DetectFlowsRequestApi {
    /**
     * GitHub repository in 'owner/repo' format, e.g. 'posthog/posthog-js'.
     * @maxLength 256
     */
    repository: string
    /**
     * Domain where the product is deployed, e.g. 'us.posthog.com'.
     * @maxLength 256
     */
    domain: string
}

export type AgenticTestRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AgenticTestsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
