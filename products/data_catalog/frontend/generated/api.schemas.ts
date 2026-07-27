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

export interface DataCatalogCertificationApi {
    readonly id: string
    /**
     * The warehouse table this mark applies to (XOR saved_query).
     * @nullable
     */
    readonly table: string | null
    /**
     * The warehouse view this mark applies to (XOR table).
     * @nullable
     */
    readonly saved_query: string | null
    /** Whether the marked target is a 'table' or a 'view'. */
    readonly target_type: string
    /** Name of the marked table or view. */
    readonly target_name: string
    /** proposed, certified (prefer this source), or deprecated (avoid this source). */
    readonly status: string
    /** Why this mark exists, e.g. 'canonical MRR source'. */
    notes?: string
    /** User who last set certified/deprecated, or null. */
    readonly certified_by: UserBasicApi | null
    /** @nullable */
    readonly certified_at: string | null
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
}

export interface PaginatedDataCatalogCertificationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataCatalogCertificationApi[]
}

/**
 * Input for proposing a certification: address the target by id or (convenience) by name.
 */
export interface CertificationCreateApi {
    /** Warehouse table id to certify (XOR the other targets). */
    table_id?: string
    /** Warehouse view (saved query) id to certify. */
    saved_query_id?: string
    /** Table name; 409 with candidates if ambiguous. */
    table_name?: string
    /** View name; 409 with candidates if ambiguous. */
    view_name?: string
    /** Why this mark exists. */
    notes?: string
}

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
 * Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.
 * @nullable
 */
export type DataCatalogMetricApiDefinition = { [key: string]: unknown } | null

export interface DataCatalogMetricApi {
    readonly id: string
    /**
     * Identifier-safe run handle, unique per team and reserved forever. Write-once.
     * @maxLength 128
     * @pattern ^[A-Za-z][A-Za-z0-9_]*$
     */
    name: string
    /**
     * Human-friendly label. Mutable, unlike name.
     * @maxLength 255
     */
    display_name?: string
    /** What the metric means and how to interpret it. */
    description: string
    /**
     * Unit of the result, e.g. usd, percent, cents.
     * @maxLength 64
     */
    unit?: string
    /**
     * Email of the human accountable for this metric, or null.
     * @nullable
     */
    readonly owner: string | null
    /**
     * Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.
     * @nullable
     */
    definition?: DataCatalogMetricApiDefinition
    /**
     * Query kind of the definition (HogQLQuery, TrendsQuery, ...), or null for a stub.
     * @nullable
     */
    readonly definition_kind: string | null
    /** Tables the definition directly references, extracted at write time for the catalog's denied-table filter. */
    readonly referenced_table_names: unknown
    /** Persisted lifecycle state: 'proposed' or 'approved'. Drift is reported separately. */
    readonly status: string
    /** True when the definition has drifted from its linked source insight (or the insight is gone). */
    readonly is_drifted: boolean
    /** @nullable */
    readonly approved_at: string | null
    /** User who approved this metric as canonical, or null. */
    readonly approved_by: UserBasicApi | null
    /**
     * Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition.
     * @maxLength 12
     * @nullable
     */
    source_insight_short_id?: string | null
    /**
     * When the metric was last run (30-minute throttle).
     * @nullable
     */
    readonly last_run_at: string | null
    /** Whether a human ('user') or an agent ('ai_generated') authored this metric.
     *
     * * `user` - user
     * * `ai_generated` - ai_generated */
    created_source?: CreatedSourceEnumApi
    /**
     * Model that generated the metric, if AI-authored.
     * @maxLength 128
     */
    ai_model?: string
    /**
     * AI author's confidence in the proposal, 0-1.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** AI author's reasoning, surfaced as review context. */
    reasoning?: string
    /** User who first created this metric. */
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedDataCatalogMetricListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataCatalogMetricApi[]
}

/**
 * Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.
 * @nullable
 */
export type PatchedDataCatalogMetricApiDefinition = { [key: string]: unknown } | null

export interface PatchedDataCatalogMetricApi {
    readonly id?: string
    /**
     * Identifier-safe run handle, unique per team and reserved forever. Write-once.
     * @maxLength 128
     * @pattern ^[A-Za-z][A-Za-z0-9_]*$
     */
    name?: string
    /**
     * Human-friendly label. Mutable, unlike name.
     * @maxLength 255
     */
    display_name?: string
    /** What the metric means and how to interpret it. */
    description?: string
    /**
     * Unit of the result, e.g. usd, percent, cents.
     * @maxLength 64
     */
    unit?: string
    /**
     * Email of the human accountable for this metric, or null.
     * @nullable
     */
    readonly owner?: string | null
    /**
     * Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.
     * @nullable
     */
    definition?: PatchedDataCatalogMetricApiDefinition
    /**
     * Query kind of the definition (HogQLQuery, TrendsQuery, ...), or null for a stub.
     * @nullable
     */
    readonly definition_kind?: string | null
    /** Tables the definition directly references, extracted at write time for the catalog's denied-table filter. */
    readonly referenced_table_names?: unknown
    /** Persisted lifecycle state: 'proposed' or 'approved'. Drift is reported separately. */
    readonly status?: string
    /** True when the definition has drifted from its linked source insight (or the insight is gone). */
    readonly is_drifted?: boolean
    /** @nullable */
    readonly approved_at?: string | null
    /** User who approved this metric as canonical, or null. */
    readonly approved_by?: UserBasicApi | null
    /**
     * Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition.
     * @maxLength 12
     * @nullable
     */
    source_insight_short_id?: string | null
    /**
     * When the metric was last run (30-minute throttle).
     * @nullable
     */
    readonly last_run_at?: string | null
    /** Whether a human ('user') or an agent ('ai_generated') authored this metric.
     *
     * * `user` - user
     * * `ai_generated` - ai_generated */
    created_source?: CreatedSourceEnumApi
    /**
     * Model that generated the metric, if AI-authored.
     * @maxLength 128
     */
    ai_model?: string
    /**
     * AI author's confidence in the proposal, 0-1.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** AI author's reasoning, surfaced as review context. */
    reasoning?: string
    /** User who first created this metric. */
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `second` - second
 * * `minute` - minute
 * * `hour` - hour
 * * `day` - day
 * * `week` - week
 * * `month` - month
 * * `quarter` - quarter
 * * `year` - year
 */
export type DataCatalogMetricRunRequestIntervalEnumApi =
    (typeof DataCatalogMetricRunRequestIntervalEnumApi)[keyof typeof DataCatalogMetricRunRequestIntervalEnumApi]

export const DataCatalogMetricRunRequestIntervalEnumApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
    Quarter: 'quarter',
    Year: 'year',
} as const

/**
 * Optional run-time overrides. The whole body may be omitted; a metric runs by its URL name.
 */
export interface DataCatalogMetricRunRequestApi {
    /** Override the start of the query window (e.g. '-7d'). Rejected for HogQLQuery metrics, whose window is fixed in SQL. */
    date_from?: string
    /** Override the end of the query window. */
    date_to?: string
    /** Override the bucket interval. Rejected for HogQLQuery metrics.
     *
     * * `second` - second
     * * `minute` - minute
     * * `hour` - hour
     * * `day` - day
     * * `week` - week
     * * `month` - month
     * * `quarter` - quarter
     * * `year` - year */
    interval?: DataCatalogMetricRunRequestIntervalEnumApi
    /** Client-supplied id to correlate or cancel the run. */
    query_id?: string
}

/**
 * Normalized envelope returned by the metric-run endpoint.
 */
export interface DataCatalogMetricRunApi {
    /** Lifecycle state of the metric that produced these results. */
    status: string
    /** True when the definition has drifted from its linked source insight (or the insight is gone). Only status 'approved' with is_drifted false is canonical. */
    is_drifted: boolean
    /**
     * Unit of the result, e.g. usd, percent.
     * @nullable
     */
    unit: string | null
    /**
     * Query kind that was executed.
     * @nullable
     */
    kind: string | null
    /** The query results, for an executable metric. Null for a markdown metric. */
    results: unknown
    /**
     * The compiled HogQL, when available.
     * @nullable
     */
    compiled_query: string | null
    /** Async query status, when the run is not blocking. */
    query_status: unknown
    /**
     * Deep link to open the query in the app (SQL editor or insight).
     * @nullable
     */
    posthog_url: string | null
    /**
     * For a markdown (agent-calculated) metric, the steps to follow to compute it. Null for an executable metric.
     * @nullable
     */
    instructions: string | null
}

export interface DataCatalogRelationshipProposalApi {
    readonly id: string
    /**
     * Name of the table the join starts from.
     * @maxLength 400
     */
    source_table_name: string
    /**
     * HogQL key expression on the source table (casts allowed).
     * @maxLength 400
     */
    source_table_key: string
    /**
     * Name of the table being joined in.
     * @maxLength 400
     */
    joining_table_name: string
    /**
     * HogQL key expression on the joining table (casts allowed).
     * @maxLength 400
     */
    joining_table_key: string
    /**
     * Accessor the join adds to the source table.
     * @maxLength 400
     */
    field_name: string
    /** Extra join configuration, e.g. a field mapping. */
    configuration?: unknown
    /**
     * Discovery confidence in this join, 0-1.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** Why this join is proposed. */
    reasoning?: string
    /** Sampling evidence: match rates, sample values. */
    evidence?: unknown
    /** proposed, accepted (promoted to a real join), or rejected (never re-proposed). */
    readonly status: string
    /** User who accepted or rejected the proposal. */
    readonly reviewed_by: UserBasicApi | null
    /** @nullable */
    readonly reviewed_at: string | null
    /** Why the proposal was rejected. */
    readonly rejection_reason: string
    /**
     * The join created when this proposal was accepted (promotion provenance).
     * @nullable
     */
    readonly created_join: string | null
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
}

export interface PaginatedDataCatalogRelationshipProposalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataCatalogRelationshipProposalApi[]
}

export interface RelationshipRejectApi {
    /** Why the proposal is rejected. Persisted so it is never re-proposed. */
    rejection_reason?: string
}

export type DataCatalogCertificationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DataCatalogMetricsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DataCatalogMetricsRunCreateParams = {
    /**
     * Cache/execution behavior, same semantics as /query/. Omit to serve a fresh cache hit and calculate blocking when stale.
     *
     * * `blocking` - blocking
     * * `async` - async
     * * `lazy_async` - lazy_async
     * * `force_blocking` - force_blocking
     * * `force_async` - force_async
     * * `force_cache` - force_cache
     * @minLength 1
     */
    refresh?: DataCatalogMetricsRunCreateRefresh
}

export type DataCatalogMetricsRunCreateRefresh =
    (typeof DataCatalogMetricsRunCreateRefresh)[keyof typeof DataCatalogMetricsRunCreateRefresh]

export const DataCatalogMetricsRunCreateRefresh = {
    Blocking: 'blocking',
    Async: 'async',
    LazyAsync: 'lazy_async',
    ForceBlocking: 'force_blocking',
    ForceAsync: 'force_async',
    ForceCache: 'force_cache',
} as const

export type DataCatalogRelationshipProposalsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by proposed/accepted/rejected.
     */
    status?: string
}
