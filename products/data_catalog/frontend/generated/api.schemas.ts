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
    /** Email of the human accountable for this metric, or null. */
    readonly owner: string
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
    /** @nullable */
    readonly approved_at: string | null
    /**
     * Short ID of the insight this metric was created from, for drift detection.
     * @nullable
     */
    readonly source_insight_short_id: string | null
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
    /** Email of the human accountable for this metric, or null. */
    readonly owner?: string
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
    /** @nullable */
    readonly approved_at?: string | null
    /**
     * Short ID of the insight this metric was created from, for drift detection.
     * @nullable
     */
    readonly source_insight_short_id?: string | null
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
