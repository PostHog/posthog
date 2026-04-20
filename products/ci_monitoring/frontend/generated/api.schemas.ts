/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface CreateQuarantineInputApi {
    /** ID of the test case to quarantine */
    test_case_id: string
    /** Reason for quarantining this test */
    reason: string
    /** Whether to auto-create a GitHub issue for tracking */
    create_github_issue?: boolean
}

/**
 * * `active` - ACTIVE
 * `resolved` - RESOLVED
 */
export type QuarantineStateEnumApi = (typeof QuarantineStateEnumApi)[keyof typeof QuarantineStateEnumApi]

export const QuarantineStateEnumApi = {
    Active: 'active',
    Resolved: 'resolved',
} as const

export interface QuarantineApi {
    id: string
    test_case_id: string
    team_id: number
    reason: string
    state: QuarantineStateEnumApi
    /** @nullable */
    github_issue_url: string | null
    /** @nullable */
    github_pr_url: string | null
    created_by_id: number
    created_at: string
    /** @nullable */
    resolved_at: string | null
    /** @nullable */
    resolved_by_id: number | null
}

export interface RepoApi {
    id: string
    team_id: number
    repo_external_id: number
    repo_full_name: string
    default_branch: string
    created_at: string
}

export interface PaginatedRepoListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RepoApi[]
}

export interface CreateRepoInputApi {
    /** GitHub numeric repository ID (stable across renames). Defaults to 0 if unknown. */
    repo_external_id?: number
    /** Full repository name (e.g., 'PostHog/posthog') */
    repo_full_name: string
    /** Default branch name */
    default_branch?: string
}

export interface MainStreakApi {
    repo_id: string
    current_streak_days: number
    /** @nullable */
    current_streak_started_at: string | null
    record_streak_days: number
    /** @nullable */
    record_streak_start: string | null
    /** @nullable */
    record_streak_end: string | null
    /** @nullable */
    last_broken_at: string | null
    last_incident_workflows?: string[]
    is_broken_now?: boolean
}

export interface CIHealthApi {
    readonly repo: RepoApi
    readonly streak: MainStreakApi
    flake_rate_7d: number
    total_runs_7d: number
    total_flaky_tests_7d: number
    tests_needing_attention: number
    active_quarantines: number
}

/**
 * * `success` - SUCCESS
 * `failure` - FAILURE
 * `cancelled` - CANCELLED
 * `timed_out` - TIMED_OUT
 */
export type CIRunConclusionEnumApi = (typeof CIRunConclusionEnumApi)[keyof typeof CIRunConclusionEnumApi]

export const CIRunConclusionEnumApi = {
    Success: 'success',
    Failure: 'failure',
    Cancelled: 'cancelled',
    TimedOut: 'timed_out',
} as const

export interface CIRunApi {
    id: string
    team_id: number
    repo_id: string
    github_run_id: number
    workflow_name: string
    commit_sha: string
    branch: string
    /** @nullable */
    pr_number: number | null
    conclusion: CIRunConclusionEnumApi
    started_at: string
    completed_at: string
    total_tests: number
    passed: number
    failed: number
    flaky: number
    skipped: number
    errored: number
    artifacts_ingested: boolean
    created_at: string
}

export interface PaginatedCIRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CIRunApi[]
}

export interface TestCaseApi {
    readonly quarantine: QuarantineApi | null
    id: string
    team_id: number
    repo_id: string
    identifier: string
    suite: string
    /** @nullable */
    file_path: string | null
    team_area: string
    flake_score: number
    total_runs: number
    total_flakes: number
    first_seen_at: string
    last_seen_at: string
    /** @nullable */
    last_flaked_at: string | null
}

export interface PaginatedTestCaseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TestCaseApi[]
}

/**
 * * `passed` - PASSED
 * `failed` - FAILED
 * `flaky` - FLAKY
 * `skipped` - SKIPPED
 * `error` - ERROR
 */
export type TestExecutionStatusEnumApi = (typeof TestExecutionStatusEnumApi)[keyof typeof TestExecutionStatusEnumApi]

export const TestExecutionStatusEnumApi = {
    Passed: 'passed',
    Failed: 'failed',
    Flaky: 'flaky',
    Skipped: 'skipped',
    Error: 'error',
} as const

export interface TestExecutionApi {
    id: string
    ci_run_id: string
    test_case_id: string
    status: TestExecutionStatusEnumApi
    /** @nullable */
    duration_ms: number | null
    /** @nullable */
    error_message: string | null
    retry_count: number
    created_at: string
}

export interface PaginatedTestExecutionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TestExecutionApi[]
}

export type CiMonitoringReposListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CiMonitoringRunsListParams = {
    /**
     * Filter by branch
     */
    branch?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by repo ID
     */
    repo_id?: string
    /**
     * Filter by workflow name
     */
    workflow_name?: string
}

export type CiMonitoringTestsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Minimum flake score
     */
    min_flake_score?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by repo ID
     */
    repo_id?: string
    /**
     * Filter by test suite
     */
    suite?: string
}

export type CiMonitoringTestsExecutionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
