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
 * * `table` - table
 * * `view` - view
 */
export type SubjectTypeEnumApi = (typeof SubjectTypeEnumApi)[keyof typeof SubjectTypeEnumApi]

export const SubjectTypeEnumApi = {
    Table: 'table',
    View: 'view',
} as const

export interface DataQualitySuiteRunApi {
    readonly id: string
    /** manual, schedule, or materialization. */
    readonly trigger: string
    /** running, completed, failed, or empty (nothing matched the trigger). */
    readonly status: string
    /** Set when the run targets exactly one subject.
     *
     * * `table` - table
     * * `view` - view */
    readonly subject_type: SubjectTypeEnumApi
    /**
     * Set when the run targets exactly one subject.
     * @nullable
     */
    readonly subject_uuid: string | null
    readonly workflow_id: string
    readonly checks_passed: number
    readonly checks_failed: number
    readonly checks_errored: number
    readonly checks_skipped: number
    /** @nullable */
    readonly started_at: string | null
    /** @nullable */
    readonly finished_at: string | null
    /** Why the suite itself failed, as opposed to an individual check. */
    readonly error: string
    readonly created_at: string
}

export interface PaginatedDataQualitySuiteRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataQualitySuiteRunApi[]
}

/**
 * * `not_null` - not_null
 * * `unique` - unique
 * * `accepted_values` - accepted_values
 * * `relationships` - relationships
 * * `row_count` - row_count
 * * `freshness` - freshness
 * * `custom_sql` - custom_sql
 */
export type CheckTypeEnumApi = (typeof CheckTypeEnumApi)[keyof typeof CheckTypeEnumApi]

export const CheckTypeEnumApi = {
    NotNull: 'not_null',
    Unique: 'unique',
    AcceptedValues: 'accepted_values',
    Relationships: 'relationships',
    RowCount: 'row_count',
    Freshness: 'freshness',
    CustomSql: 'custom_sql',
} as const

export interface DataQualityCheckRunApi {
    readonly id: string
    /**
     * The definition executed. Nulled rather than cascaded so history outlives hard deletes.
     * @nullable
     */
    readonly quality_check: string | null
    readonly suite_run: string
    readonly subject_type: SubjectTypeEnumApi
    readonly subject_uuid: string
    readonly subject_name: string
    readonly check_type: CheckTypeEnumApi
    readonly column_name: string
    /** passed, failed, errored, or skipped. */
    readonly status: string
    /**
     * Rows violating the assertion. Null for bounds checks like row_count.
     * @nullable
     */
    readonly failed_row_count: number | null
    /**
     * The check's headline number, recorded on passes too.
     * @nullable
     */
    readonly observed_value: number | null
    /** The HogQL that ran. Re-run it to see the offending rows. */
    readonly compiled_query: string
    /** Compilation or execution failure, when status is 'errored'. */
    readonly error: string
    /** @nullable */
    readonly duration_ms: number | null
    /** @nullable */
    readonly started_at: string | null
    /** @nullable */
    readonly finished_at: string | null
    readonly created_at: string
}

/**
 * * `error` - error
 * * `warn` - warn
 */
export type DataQualityCheckSeverityEnumApi =
    (typeof DataQualityCheckSeverityEnumApi)[keyof typeof DataQualityCheckSeverityEnumApi]

export const DataQualityCheckSeverityEnumApi = {
    Error: 'error',
    Warn: 'warn',
} as const

/**
 * * `user` - user
 * * `ai_generated` - ai_generated
 */
export type CreatedSourceEnumApi = (typeof CreatedSourceEnumApi)[keyof typeof CreatedSourceEnumApi]

export const CreatedSourceEnumApi = {
    User: 'user',
    AiGenerated: 'ai_generated',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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
 * Type-specific configuration, validated against the check type's JSON schema.
 */
export type DataQualityCheckApiConfig = { [key: string]: unknown }

export interface DataQualityCheckApi {
    readonly id: string
    /**
     * Optional identifier-safe handle, unique per project. Omit to address the check by id.
     * @maxLength 128
     * @pattern ^[A-Za-z][A-Za-z0-9_]*$
     */
    name?: string
    /** Why this check exists and what a failure means. */
    description?: string
    /** Kind of catalog object being checked: 'table' (a synced warehouse table) or 'view' (a saved query).
     *
     * * `table` - table
     * * `view` - view */
    subject_type: SubjectTypeEnumApi
    /** Id of the table or view being checked. */
    subject_uuid: string
    /** Queryable name of the subject, refreshed on every run. */
    readonly subject_name: string
    /** 'orphaned' once the subject stops resolving. Orphaned checks are skipped, not deleted. */
    readonly subject_status: string
    /**
     * Column the check applies to. Omit for table-scoped types like row_count.
     * @maxLength 400
     */
    column_name?: string
    /** Which assertion to make. Determines the shape of config; see /check_types/.
     *
     * * `not_null` - not_null
     * * `unique` - unique
     * * `accepted_values` - accepted_values
     * * `relationships` - relationships
     * * `row_count` - row_count
     * * `freshness` - freshness
     * * `custom_sql` - custom_sql */
    check_type: CheckTypeEnumApi
    /** Type-specific configuration, validated against the check type's JSON schema. */
    config?: DataQualityCheckApiConfig
    /** 'error' failures mark the subject failing and notify; 'warn' failures only surface.
     *
     * * `error` - error
     * * `warn` - warn */
    severity?: DataQualityCheckSeverityEnumApi
    /** Disabled checks are never run by any trigger. */
    enabled?: boolean
    /** Free-form labels for grouping and filtering. */
    tags?: unknown
    /**
     * Email of the human accountable for this check, or null.
     * @nullable
     */
    readonly owner: string | null
    /** Run after the view materializes. Never delays or fails the materialization itself. */
    run_on_materialization?: boolean
    /**
     * Independent cadence in minutes. Omit for no schedule of its own.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    schedule_interval_minutes?: number | null
    /**
     * When the due-checks scanner should next pick this check up.
     * @nullable
     */
    readonly next_run_at: string | null
    /**
     * When the check last executed.
     * @nullable
     */
    readonly last_run_at: string | null
    /** Outcome of the newest run: passed, failed, errored, skipped, or empty if never run. */
    readonly last_status: string
    /** sha256 of the subject, type, column, and config. Re-creating the same check upserts. */
    readonly fingerprint: string
    /** Whether a human ('user') or an agent ('ai_generated') authored this check.
     *
     * * `user` - user
     * * `ai_generated` - ai_generated */
    created_source?: CreatedSourceEnumApi
    /**
     * Model that generated the check, if AI-authored.
     * @maxLength 128
     */
    ai_model?: string
    /**
     * AI author's confidence in the check, 0-1.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** AI author's reasoning, surfaced as review context. */
    reasoning?: string
    /** User who first created this check. */
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedDataQualityCheckListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataQualityCheckApi[]
}

/**
 * Type-specific configuration, validated against the check type's JSON schema.
 */
export type PatchedDataQualityCheckApiConfig = { [key: string]: unknown }

export interface PatchedDataQualityCheckApi {
    readonly id?: string
    /**
     * Optional identifier-safe handle, unique per project. Omit to address the check by id.
     * @maxLength 128
     * @pattern ^[A-Za-z][A-Za-z0-9_]*$
     */
    name?: string
    /** Why this check exists and what a failure means. */
    description?: string
    /** Kind of catalog object being checked: 'table' (a synced warehouse table) or 'view' (a saved query).
     *
     * * `table` - table
     * * `view` - view */
    subject_type?: SubjectTypeEnumApi
    /** Id of the table or view being checked. */
    subject_uuid?: string
    /** Queryable name of the subject, refreshed on every run. */
    readonly subject_name?: string
    /** 'orphaned' once the subject stops resolving. Orphaned checks are skipped, not deleted. */
    readonly subject_status?: string
    /**
     * Column the check applies to. Omit for table-scoped types like row_count.
     * @maxLength 400
     */
    column_name?: string
    /** Which assertion to make. Determines the shape of config; see /check_types/.
     *
     * * `not_null` - not_null
     * * `unique` - unique
     * * `accepted_values` - accepted_values
     * * `relationships` - relationships
     * * `row_count` - row_count
     * * `freshness` - freshness
     * * `custom_sql` - custom_sql */
    check_type?: CheckTypeEnumApi
    /** Type-specific configuration, validated against the check type's JSON schema. */
    config?: PatchedDataQualityCheckApiConfig
    /** 'error' failures mark the subject failing and notify; 'warn' failures only surface.
     *
     * * `error` - error
     * * `warn` - warn */
    severity?: DataQualityCheckSeverityEnumApi
    /** Disabled checks are never run by any trigger. */
    enabled?: boolean
    /** Free-form labels for grouping and filtering. */
    tags?: unknown
    /**
     * Email of the human accountable for this check, or null.
     * @nullable
     */
    readonly owner?: string | null
    /** Run after the view materializes. Never delays or fails the materialization itself. */
    run_on_materialization?: boolean
    /**
     * Independent cadence in minutes. Omit for no schedule of its own.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    schedule_interval_minutes?: number | null
    /**
     * When the due-checks scanner should next pick this check up.
     * @nullable
     */
    readonly next_run_at?: string | null
    /**
     * When the check last executed.
     * @nullable
     */
    readonly last_run_at?: string | null
    /** Outcome of the newest run: passed, failed, errored, skipped, or empty if never run. */
    readonly last_status?: string
    /** sha256 of the subject, type, column, and config. Re-creating the same check upserts. */
    readonly fingerprint?: string
    /** Whether a human ('user') or an agent ('ai_generated') authored this check.
     *
     * * `user` - user
     * * `ai_generated` - ai_generated */
    created_source?: CreatedSourceEnumApi
    /**
     * Model that generated the check, if AI-authored.
     * @maxLength 128
     */
    ai_model?: string
    /**
     * AI author's confidence in the check, 0-1.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** AI author's reasoning, surfaced as review context. */
    reasoning?: string
    /** User who first created this check. */
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * JSON schema the config object is validated against.
 */
export type DataQualityCheckTypeApiConfigSchema = { [key: string]: unknown }

/**
 * One entry of the check-type catalog, so an agent can author config without guessing.
 */
export interface DataQualityCheckTypeApi {
    /** Value to pass as check_type. */
    check_type: string
    /** What the check asserts and what counts as a failure. */
    description: string
    /** Whether column_name must be set for this type. */
    requires_column: boolean
    /** JSON schema the config object is validated against. */
    config_schema: DataQualityCheckTypeApiConfigSchema
}

/**
 * Per-subject rollup, the same rule the information_schema.data_quality_health table uses.
 */
export interface DataQualitySubjectHealthApi {
    /** 'table' or 'view'. */
    subject_type: string
    /** Id of the table or view. */
    subject_uuid: string
    /** failing (an error-severity check failed), erroring (a check could not run), warn (only warn-severity failures), healthy, or unknown (nothing has run yet). */
    health: string
    /** How many enabled, non-deleted checks cover this subject. */
    checks_total: number
    /** How many of those checks last reported a failure. */
    checks_failing: number
}

export interface DataQualityRunSubjectRequestApi {
    /** 'table' or 'view'.
     *
     * * `table` - table
     * * `view` - view */
    subject_type: SubjectTypeEnumApi
    /** Id of the table or view whose checks should run. */
    subject_uuid: string
}

export type DataQualityCheckSuiteRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DataQualityChecksListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DataQualityChecksCreateParams = {
    /**
     * Filter the list to one check type.
     */
    check_type?: string
    /**
     * Filter the list to 'table' or 'view' subjects.
     */
    subject_type?: string
    /**
     * Filter the list to one table or view.
     */
    subject_uuid?: string
}

export type DataQualityChecksHealthRetrieveParams = {
    /**
     * 'table' or 'view'.
     *
     * * `table` - table
     * * `view` - view
     * @minLength 1
     */
    subject_type: DataQualityChecksHealthRetrieveSubjectType
    /**
     * Id of the table or view to roll up.
     */
    subject_uuid: string
}

export type DataQualityChecksHealthRetrieveSubjectType =
    (typeof DataQualityChecksHealthRetrieveSubjectType)[keyof typeof DataQualityChecksHealthRetrieveSubjectType]

export const DataQualityChecksHealthRetrieveSubjectType = {
    Table: 'table',
    View: 'view',
} as const
