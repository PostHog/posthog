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
 * * `metric` - metric
 * * `posthog_table` - posthog_table
 */
export type SubjectTypeEnumApi = (typeof SubjectTypeEnumApi)[keyof typeof SubjectTypeEnumApi]

export const SubjectTypeEnumApi = {
    Table: 'table',
    View: 'view',
    Metric: 'metric',
    PosthogTable: 'posthog_table',
} as const

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
 * * `student` - Student
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
    Student: 'student',
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
export type DataQualityOverviewCheckApiConfig = { [key: string]: unknown }

/**
 * A check plus where its subject can be opened, for the project-wide list.
 *
 * The per-subject surfaces already know their parent; only this one lists checks across every
 * table and view, so only this one needs to say where each subject lives. The ids are resolved
 * for a whole page at once and handed in through ``subject_locations`` in the context.
 */
export interface DataQualityOverviewCheckApi {
    readonly id: string
    /** Optional identifier-safe handle, unique per project. Omit to address the check by id. */
    name?: string
    /** Why this check exists and what a failure means. */
    description?: string
    /** Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    readonly subject_type: SubjectTypeEnumApi
    /**
     * Id of the table, view, metric, or PostHog table being checked. Null once the subject is deleted.
     * @nullable
     */
    readonly subject_uuid: string | null
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
    config?: DataQualityOverviewCheckApiConfig
    /** 'error' failures mark the subject failing and notify; 'warn' failures only surface.
     *
     * * `error` - error
     * * `warn` - warn */
    severity?: DataQualityCheckSeverityEnumApi
    /** Disabled checks are never run by any trigger. */
    enabled?: boolean
    /** Free-form string labels for grouping and filtering. */
    tags?: string[]
    /**
     * Email of the human accountable for this check, or null.
     * @nullable
     */
    readonly owner: string | null
    /**
     * When the check last executed.
     * @nullable
     */
    readonly last_run_at: string | null
    /** Outcome of the newest run: passed, failed, errored, skipped, or empty if never run. */
    readonly last_status: string
    /**
     * When the check last passed. Read failing_since for how long a failing check has been failing. Null means it has not passed within the run retention window.
     * @nullable
     */
    readonly last_succeeded_at: string | null
    /**
     * When the current streak of failing runs started, so a failing check can say how long it has been failing. Null when the check is not failing.
     * @nullable
     */
    readonly failing_since: string | null
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
    /**
     * Data modeling node of the view or PostHog table this check audits, or null when it is on no DAG or the subject is a warehouse table.
     * @nullable
     */
    readonly subject_node_id: string | null
    /**
     * Warehouse source of the table this check audits, or null when the subject is a view.
     * @nullable
     */
    readonly subject_source_id: string | null
    /**
     * Warehouse source schema of the table this check audits, or null when the subject is a view.
     * @nullable
     */
    readonly subject_schema_id: string | null
    /**
     * Current metric name for opening its Tests tab, or null for other subjects.
     * @nullable
     */
    readonly subject_metric_name: string | null
}

export interface PaginatedDataQualityOverviewCheckListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataQualityOverviewCheckApi[]
}

/**
 * Type-specific configuration, validated against the check type's JSON schema.
 */
export type DataQualityCheckCreateApiConfig = { [key: string]: unknown }

/**
 * The create body, where the subject is named for the only time in a check's life.
 */
export interface DataQualityCheckCreateApi {
    readonly id: string
    /** Optional identifier-safe handle, unique per project. Omit to address the check by id. */
    name?: string
    /** Why this check exists and what a failure means. */
    description?: string
    /** Kind of object to check: 'table', 'view', 'metric', or 'posthog_table'.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    subject_type: SubjectTypeEnumApi
    /** Id of the table, view, metric, or PostHog table to check. */
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
    config?: DataQualityCheckCreateApiConfig
    /** 'error' failures mark the subject failing and notify; 'warn' failures only surface.
     *
     * * `error` - error
     * * `warn` - warn */
    severity?: DataQualityCheckSeverityEnumApi
    /** Disabled checks are never run by any trigger. */
    enabled?: boolean
    /** Free-form string labels for grouping and filtering. */
    tags?: string[]
    /**
     * Email of the human accountable for this check, or null.
     * @nullable
     */
    readonly owner: string | null
    /**
     * When the check last executed.
     * @nullable
     */
    readonly last_run_at: string | null
    /** Outcome of the newest run: passed, failed, errored, skipped, or empty if never run. */
    readonly last_status: string
    /**
     * When the check last passed. Read failing_since for how long a failing check has been failing. Null means it has not passed within the run retention window.
     * @nullable
     */
    readonly last_succeeded_at: string | null
    /**
     * When the current streak of failing runs started, so a failing check can say how long it has been failing. Null when the check is not failing.
     * @nullable
     */
    readonly failing_since: string | null
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

/**
 * Type-specific configuration, validated against the check type's JSON schema.
 */
export type DataQualityCheckApiConfig = { [key: string]: unknown }

/**
 * A check as it reads back, and everything an edit may change about it.
 *
 * The subject is not one of those: it is writable only on ``DataQualityCheckCreate``.
 */
export interface DataQualityCheckApi {
    readonly id: string
    /** Optional identifier-safe handle, unique per project. Omit to address the check by id. */
    name?: string
    /** Why this check exists and what a failure means. */
    description?: string
    /** Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    readonly subject_type: SubjectTypeEnumApi
    /**
     * Id of the table, view, metric, or PostHog table being checked. Null once the subject is deleted.
     * @nullable
     */
    readonly subject_uuid: string | null
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
    /** Free-form string labels for grouping and filtering. */
    tags?: string[]
    /**
     * Email of the human accountable for this check, or null.
     * @nullable
     */
    readonly owner: string | null
    /**
     * When the check last executed.
     * @nullable
     */
    readonly last_run_at: string | null
    /** Outcome of the newest run: passed, failed, errored, skipped, or empty if never run. */
    readonly last_status: string
    /**
     * When the check last passed. Read failing_since for how long a failing check has been failing. Null means it has not passed within the run retention window.
     * @nullable
     */
    readonly last_succeeded_at: string | null
    /**
     * When the current streak of failing runs started, so a failing check can say how long it has been failing. Null when the check is not failing.
     * @nullable
     */
    readonly failing_since: string | null
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

/**
 * Type-specific configuration, validated against the check type's JSON schema.
 */
export type PatchedDataQualityCheckApiConfig = { [key: string]: unknown }

/**
 * A check as it reads back, and everything an edit may change about it.
 *
 * The subject is not one of those: it is writable only on ``DataQualityCheckCreate``.
 */
export interface PatchedDataQualityCheckApi {
    readonly id?: string
    /** Optional identifier-safe handle, unique per project. Omit to address the check by id. */
    name?: string
    /** Why this check exists and what a failure means. */
    description?: string
    /** Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    readonly subject_type?: SubjectTypeEnumApi
    /**
     * Id of the table, view, metric, or PostHog table being checked. Null once the subject is deleted.
     * @nullable
     */
    readonly subject_uuid?: string | null
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
    /** Free-form string labels for grouping and filtering. */
    tags?: string[]
    /**
     * Email of the human accountable for this check, or null.
     * @nullable
     */
    readonly owner?: string | null
    /**
     * When the check last executed.
     * @nullable
     */
    readonly last_run_at?: string | null
    /** Outcome of the newest run: passed, failed, errored, skipped, or empty if never run. */
    readonly last_status?: string
    /**
     * When the check last passed. Read failing_since for how long a failing check has been failing. Null means it has not passed within the run retention window.
     * @nullable
     */
    readonly last_succeeded_at?: string | null
    /**
     * When the current streak of failing runs started, so a failing check can say how long it has been failing. Null when the check is not failing.
     * @nullable
     */
    readonly failing_since?: string | null
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

export interface DataQualitySuiteRunApi {
    readonly id: string
    /** manual, materialization, source_sync, or scheduled. */
    readonly trigger: string
    /** running, completed, failed, or empty (nothing matched the trigger). */
    readonly status: string
    /**
     * 'table', 'view', 'metric', or 'posthog_table' when the run targets exactly one subject, including a run of a single check on that subject; null for a run spanning several subjects.
     * @nullable
     */
    readonly subject_type: string | null
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

/**
 * Config this run executed, snapshotted so an edit to the check cannot rewrite history. Null for runs recorded before snapshots existed -- unknown, not 'same as the check has now'.
 * @nullable
 */
export type DataQualityCheckRunApiCheckConfig = { [key: string]: unknown } | null

export interface DataQualityCheckRunApi {
    readonly id: string
    /**
     * The definition executed. Nulled rather than cascaded so history outlives hard deletes.
     * @nullable
     */
    readonly quality_check: string | null
    /**
     * Name the check carries now, so a run can be told from the others in its suite. Null when the check is unnamed, has been hard deleted, or is out of your reach today -- describe the run by check_type and column_name instead.
     * @nullable
     */
    readonly check_name: string | null
    readonly suite_run: string
    readonly subject_type: SubjectTypeEnumApi
    readonly subject_uuid: string
    readonly subject_name: string
    /** Which assertion this run made.
     *
     * * `not_null` - not_null
     * * `unique` - unique
     * * `accepted_values` - accepted_values
     * * `relationships` - relationships
     * * `row_count` - row_count
     * * `freshness` - freshness
     * * `custom_sql` - custom_sql */
    readonly check_type: CheckTypeEnumApi
    readonly column_name: string
    /**
     * Config this run executed, snapshotted so an edit to the check cannot rewrite history. Null for runs recorded before snapshots existed -- unknown, not 'same as the check has now'.
     * @nullable
     */
    readonly check_config: DataQualityCheckRunApiCheckConfig
    /** Severity this run was judged at. Null for runs recorded before snapshots existed.
     *
     * * `error` - error
     * * `warn` - warn */
    readonly check_severity: DataQualityCheckSeverityEnumApi | null
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
    /** 'table', 'view', 'metric', or 'posthog_table'. */
    subject_type: string
    /** Id of the table, view, metric, or PostHog table. */
    subject_uuid: string
    /** failing (an error-severity check failed), erroring (a check could not run), warn (only warn-severity failures), healthy, or unknown (nothing has run yet). */
    health: string
    /** How many enabled, non-deleted checks cover this subject. */
    checks_total: number
    /** How many of those checks last reported a failure. */
    checks_failing: number
}

export interface DataQualityMetricSubjectApi {
    /** Metric identifier used by the nested check endpoints. */
    id: string
    /** Queryable metric name. */
    name: string
    /** Metric label shown in the data catalog. */
    display_name: string
}

export interface DataQualityOutputColumnApi {
    /** Output column name available through the {metric} relation. */
    name: string
    /**
     * ClickHouse type, or null when it could not be inferred.
     * @nullable
     */
    type: string | null
}

export interface DataQualityOutputSchemaApi {
    /** Columns returned by the saved metric query. */
    columns: DataQualityOutputColumnApi[]
}

/**
 * * `1hour` - 1hour
 * * `6hour` - 6hour
 * * `12hour` - 12hour
 * * `24hour` - 24hour
 * * `7day` - 7day
 */
export type DataQualityScheduleIntervalEnumApi =
    (typeof DataQualityScheduleIntervalEnumApi)[keyof typeof DataQualityScheduleIntervalEnumApi]

export const DataQualityScheduleIntervalEnumApi = {
    '1hour': '1hour',
    '6hour': '6hour',
    '12hour': '12hour',
    '24hour': '24hour',
    '7day': '7day',
} as const

export interface DataQualityCheckScheduleApi {
    /** Schedule identifier. */
    readonly id: string
    /** How often the checks run.
     *
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day */
    readonly interval: DataQualityScheduleIntervalEnumApi
    /** Whether the schedule runs automatically. */
    readonly enabled: boolean
    /**
     * Next scheduled execution time, if enabled.
     * @nullable
     */
    readonly next_run_at: string | null
    /**
     * Most recent visible scheduled suite execution time.
     * @nullable
     */
    readonly last_run_at: string | null
    /**
     * Most recent visible scheduled suite.
     * @nullable
     */
    readonly last_suite_run: string | null
}

/**
 * Which subject's schedule to change, and what to change about it.
 */
export interface PatchedDataQualityCheckScheduleUpdateApi {
    /** Kind of object: 'table', 'view', 'metric', or 'posthog_table'.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    subject_type?: SubjectTypeEnumApi
    /** Id of the table, view, metric, or PostHog table. */
    subject_uuid?: string
    /** How often all enabled checks on the subject run.
     *
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day */
    interval?: DataQualityScheduleIntervalEnumApi
    /** Whether checks run automatically on this schedule. */
    enabled?: boolean
}

/**
 * One subject's schedule, in the project-wide listing.
 */
export interface DataQualitySubjectScheduleApi {
    /** Schedule identifier. */
    readonly id: string
    /** How often the checks run.
     *
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day */
    readonly interval: DataQualityScheduleIntervalEnumApi
    /** Whether the schedule runs automatically. */
    readonly enabled: boolean
    /**
     * Next scheduled execution time, if enabled.
     * @nullable
     */
    readonly next_run_at: string | null
    /**
     * Most recent visible scheduled suite execution time.
     * @nullable
     */
    readonly last_run_at: string | null
    /**
     * Most recent visible scheduled suite.
     * @nullable
     */
    readonly last_suite_run: string | null
    /** 'metric' or 'posthog_table'.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    readonly subject_type: SubjectTypeEnumApi
    /** Id of the metric or PostHog table. */
    readonly subject_uuid: string
}

/**
 * Column name to ClickHouse type. Empty for a metric, and for a view that has not run yet.
 */
export type DataQualitySubjectApiColumns = { [key: string]: string }

/**
 * One thing a check can be authored on, whatever kind it is.
 */
export interface DataQualitySubjectApi {
    /** Kind of object: 'table', 'view', 'metric', or 'posthog_table'. Pass it back as subject_type when creating a check.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    subject_type: SubjectTypeEnumApi
    /** Id of the subject. Pass it back as subject_uuid when creating a check. */
    id: string
    /** Queryable name of the subject. */
    name: string
    /** Label shown in the data catalog. Blank for tables and views. */
    display_name: string
    /** Column a lookback window bounds, or blank for a subject that has none. */
    time_column: string
    /** Column name to ClickHouse type. Empty for a metric, and for a view that has not run yet. */
    columns: DataQualitySubjectApiColumns
    /** Whether the caller may author a check on this subject. A subject that is only readable can still be the target of a relationships check. */
    editable: boolean
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
 * What to run in a project-wide suite run.
 */
export interface DataQualityRunRequestApi {
    /** Ids of the checks to run. Omit to run every enabled check in the project. */
    check_ids?: string[]
    /** Narrow the run to one subject. Pass subject_uuid with it. Ignored when check_ids is given.
     *
     * * `table` - table
     * * `view` - view
     * * `metric` - metric
     * * `posthog_table` - posthog_table */
    subject_type?: SubjectTypeEnumApi
    /** Id of the subject to run every enabled check on. Pass subject_type with it. */
    subject_uuid?: string
}

export type DataQualityChecksListParams = {
    /**
     * Only the checks that make this assertion. See /check_types/.
     */
    check_type?: DataQualityChecksListCheckType
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     */
    subject_type?: DataQualityChecksListSubjectType
    /**
     * Id of the table, view, metric, or PostHog table.
     */
    subject_uuid?: string
}

export type DataQualityChecksListCheckType =
    (typeof DataQualityChecksListCheckType)[keyof typeof DataQualityChecksListCheckType]

export const DataQualityChecksListCheckType = {
    AcceptedValues: 'accepted_values',
    CustomSql: 'custom_sql',
    Freshness: 'freshness',
    NotNull: 'not_null',
    Relationships: 'relationships',
    RowCount: 'row_count',
    Unique: 'unique',
} as const

export type DataQualityChecksListSubjectType =
    (typeof DataQualityChecksListSubjectType)[keyof typeof DataQualityChecksListSubjectType]

export const DataQualityChecksListSubjectType = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    Table: 'table',
    View: 'view',
} as const

export type DataQualityChecksCheckTypesListParams = {
    /**
     * Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     */
    subject_type?: DataQualityChecksCheckTypesListSubjectType
}

export type DataQualityChecksCheckTypesListSubjectType =
    (typeof DataQualityChecksCheckTypesListSubjectType)[keyof typeof DataQualityChecksCheckTypesListSubjectType]

export const DataQualityChecksCheckTypesListSubjectType = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    Table: 'table',
    View: 'view',
} as const

export type DataQualityChecksHealthListParams = {
    /**
     * Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     */
    subject_type?: DataQualityChecksHealthListSubjectType
    /**
     * Id of the table, view, metric, or PostHog table.
     */
    subject_uuid?: string
}

export type DataQualityChecksHealthListSubjectType =
    (typeof DataQualityChecksHealthListSubjectType)[keyof typeof DataQualityChecksHealthListSubjectType]

export const DataQualityChecksHealthListSubjectType = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    Table: 'table',
    View: 'view',
} as const

export type DataQualityChecksOutputSchemaRetrieveParams = {
    /**
     * Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     */
    subject_type?: DataQualityChecksOutputSchemaRetrieveSubjectType
    /**
     * Id of the table, view, metric, or PostHog table.
     */
    subject_uuid?: string
}

export type DataQualityChecksOutputSchemaRetrieveSubjectType =
    (typeof DataQualityChecksOutputSchemaRetrieveSubjectType)[keyof typeof DataQualityChecksOutputSchemaRetrieveSubjectType]

export const DataQualityChecksOutputSchemaRetrieveSubjectType = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    Table: 'table',
    View: 'view',
} as const

export type DataQualityChecksScheduleRetrieveParams = {
    /**
     * Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     */
    subject_type?: DataQualityChecksScheduleRetrieveSubjectType
    /**
     * Id of the table, view, metric, or PostHog table.
     */
    subject_uuid?: string
}

export type DataQualityChecksScheduleRetrieveSubjectType =
    (typeof DataQualityChecksScheduleRetrieveSubjectType)[keyof typeof DataQualityChecksScheduleRetrieveSubjectType]

export const DataQualityChecksScheduleRetrieveSubjectType = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    Table: 'table',
    View: 'view',
} as const

export type DataQualityRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.
     */
    subject_type?: DataQualityRunsListSubjectType
    /**
     * Id of the table, view, metric, or PostHog table.
     */
    subject_uuid?: string
}

export type DataQualityRunsListSubjectType =
    (typeof DataQualityRunsListSubjectType)[keyof typeof DataQualityRunsListSubjectType]

export const DataQualityRunsListSubjectType = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    Table: 'table',
    View: 'view',
} as const
