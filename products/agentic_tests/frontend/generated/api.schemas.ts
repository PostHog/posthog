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

export interface AgenticTestRunApi {
    readonly id: string
    readonly agentic_test: string
    readonly started_at: string
    /** @nullable */
    readonly finished_at: string | null
    readonly status: AgenticTestRunStatusEnumApi
    /** @nullable */
    readonly duration_ms: number | null
    /** Raw response from the browser agent. */
    readonly output: unknown
    readonly error_message: string
    /** Runner-specific session id (e.g. browserbase) so we can deep-link back to the agent run. */
    readonly external_session_id: string
    readonly screenshot_url: string
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

/**
 * Most recent run for this test, or null if none have completed yet.
 * @nullable
 */
export type AgenticTestApiLastRun = { [key: string]: unknown } | null

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
    /** List of post-run checks the test must satisfy in addition to the agent's own self-evaluation. Each item: {type, ...config}. Supported types: url_contains, event_captured. */
    assertions?: unknown
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
    /**
     * Most recent run for this test, or null if none have completed yet.
     * @nullable
     */
    readonly last_run: AgenticTestApiLastRun
}

export interface PaginatedAgenticTestListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgenticTestApi[]
}

/**
 * Most recent run for this test, or null if none have completed yet.
 * @nullable
 */
export type PatchedAgenticTestApiLastRun = { [key: string]: unknown } | null

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
    /** List of post-run checks the test must satisfy in addition to the agent's own self-evaluation. Each item: {type, ...config}. Supported types: url_contains, event_captured. */
    assertions?: unknown
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
    /**
     * Most recent run for this test, or null if none have completed yet.
     * @nullable
     */
    readonly last_run?: PatchedAgenticTestApiLastRun
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
