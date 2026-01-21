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
 * * `Running` - Running
 * `Completed` - Completed
 * `Failed` - Failed
 * `Cancelled` - Cancelled
 */
export type DataModelingJobStatusEnumApi =
    (typeof DataModelingJobStatusEnumApi)[keyof typeof DataModelingJobStatusEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataModelingJobStatusEnumApi = {
    Running: 'Running',
    Completed: 'Completed',
    Failed: 'Failed',
    Cancelled: 'Cancelled',
} as const

export interface DataModelingJobApi {
    readonly id: string
    /** @nullable */
    readonly saved_query_id: string | null
    readonly status: DataModelingJobStatusEnumApi
    readonly rows_materialized: number
    /** @nullable */
    readonly error: string | null
    readonly created_at: string
    readonly last_run_at: string
    /** @nullable */
    readonly workflow_id: string | null
    /** @nullable */
    readonly workflow_run_id: string | null
    /**
     * Total rows expected to be materialized
     * @nullable
     */
    readonly rows_expected: number | null
}

export interface PaginatedDataModelingJobListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataModelingJobApi[]
}

/**
 * * `Ashby` - Ashby
 * `Supabase` - Supabase
 * `CustomerIO` - CustomerIO
 * `Github` - Github
 * `Stripe` - Stripe
 * `Hubspot` - Hubspot
 * `Postgres` - Postgres
 * `Zendesk` - Zendesk
 * `Snowflake` - Snowflake
 * `Salesforce` - Salesforce
 * `MySQL` - MySQL
 * `MongoDB` - MongoDB
 * `MSSQL` - MSSQL
 * `Vitally` - Vitally
 * `BigQuery` - BigQuery
 * `Chargebee` - Chargebee
 * `GoogleAds` - GoogleAds
 * `TemporalIO` - TemporalIO
 * `DoIt` - DoIt
 * `GoogleSheets` - GoogleSheets
 * `MetaAds` - MetaAds
 * `Klaviyo` - Klaviyo
 * `Mailchimp` - Mailchimp
 * `Braze` - Braze
 * `Mailjet` - Mailjet
 * `Redshift` - Redshift
 * `Polar` - Polar
 * `RevenueCat` - RevenueCat
 * `LinkedinAds` - LinkedinAds
 * `RedditAds` - RedditAds
 * `TikTokAds` - TikTokAds
 * `BingAds` - BingAds
 * `Shopify` - Shopify
 */
export type SourceTypeEnumApi = (typeof SourceTypeEnumApi)[keyof typeof SourceTypeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SourceTypeEnumApi = {
    Ashby: 'Ashby',
    Supabase: 'Supabase',
    CustomerIO: 'CustomerIO',
    Github: 'Github',
    Stripe: 'Stripe',
    Hubspot: 'Hubspot',
    Postgres: 'Postgres',
    Zendesk: 'Zendesk',
    Snowflake: 'Snowflake',
    Salesforce: 'Salesforce',
    MySQL: 'MySQL',
    MongoDB: 'MongoDB',
    MSSQL: 'MSSQL',
    Vitally: 'Vitally',
    BigQuery: 'BigQuery',
    Chargebee: 'Chargebee',
    GoogleAds: 'GoogleAds',
    TemporalIO: 'TemporalIO',
    DoIt: 'DoIt',
    GoogleSheets: 'GoogleSheets',
    MetaAds: 'MetaAds',
    Klaviyo: 'Klaviyo',
    Mailchimp: 'Mailchimp',
    Braze: 'Braze',
    Mailjet: 'Mailjet',
    Redshift: 'Redshift',
    Polar: 'Polar',
    RevenueCat: 'RevenueCat',
    LinkedinAds: 'LinkedinAds',
    RedditAds: 'RedditAds',
    TikTokAds: 'TikTokAds',
    BingAds: 'BingAds',
    Shopify: 'Shopify',
} as const

export interface ExternalDataSourceRevenueAnalyticsConfigApi {
    enabled?: boolean
    include_invoiceless_charges?: boolean
}

/**
 * Mixin for serializers to add user access control fields
 */
export interface ExternalDataSourceSerializersApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly created_by: string | null
    readonly status: string
    client_secret: string
    account_id: string
    readonly source_type: SourceTypeEnumApi
    readonly latest_error: string
    /** @nullable */
    readonly prefix: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly last_run_at: string
    readonly schemas: string
    job_inputs?: unknown
    readonly revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExternalDataSourceSerializersListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSourceSerializersApi[]
}

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedExternalDataSourceSerializersApi {
    readonly id?: string
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: string | null
    readonly status?: string
    client_secret?: string
    account_id?: string
    readonly source_type?: SourceTypeEnumApi
    readonly latest_error?: string
    /** @nullable */
    readonly prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly last_run_at?: string
    readonly schemas?: string
    job_inputs?: unknown
    readonly revenue_analytics_config?: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RoleAtOrganizationEnumApi = {
    engineering: 'engineering',
    data: 'data',
    product: 'product',
    founder: 'founder',
    leadership: 'leadership',
    marketing: 'marketing',
    sales: 'sales',
    other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi
}

/**
 * * `Cancelled` - Cancelled
 * `Modified` - Modified
 * `Completed` - Completed
 * `Failed` - Failed
 * `Running` - Running
 */
export type StatusD5cEnumApi = (typeof StatusD5cEnumApi)[keyof typeof StatusD5cEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const StatusD5cEnumApi = {
    Cancelled: 'Cancelled',
    Modified: 'Modified',
    Completed: 'Completed',
    Failed: 'Failed',
    Running: 'Running',
} as const

/**
 * * `data_warehouse` - Data Warehouse
 * `endpoint` - Endpoint
 * `managed_viewset` - Managed Viewset
 */
export type OriginEnumApi = (typeof OriginEnumApi)[keyof typeof OriginEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const OriginEnumApi = {
    data_warehouse: 'data_warehouse',
    endpoint: 'endpoint',
    managed_viewset: 'managed_viewset',
} as const

/**
 * Lightweight serializer for list views - excludes large query field to reduce memory usage.
 */
export interface DataWarehouseSavedQueryMinimalApi {
    readonly id: string
    /** @nullable */
    readonly deleted: boolean | null
    readonly name: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly sync_frequency: string
    readonly columns: string
    /** The status of when this SavedQuery last ran.

* `Cancelled` - Cancelled
* `Modified` - Modified
* `Completed` - Completed
* `Failed` - Failed
* `Running` - Running */
    readonly status: StatusD5cEnumApi | NullEnumApi
    /** @nullable */
    readonly last_run_at: string | null
    readonly managed_viewset_kind: string
    /** @nullable */
    readonly latest_error: string | null
    /** @nullable */
    readonly is_materialized: boolean | null
    /** Where this SavedQuery is created.

* `data_warehouse` - Data Warehouse
* `endpoint` - Endpoint
* `managed_viewset` - Managed Viewset */
    readonly origin: OriginEnumApi | NullEnumApi
}

export interface PaginatedDataWarehouseSavedQueryMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataWarehouseSavedQueryMinimalApi[]
}

/**
 * Shared methods for DataWarehouseSavedQuery serializers.

This mixin is intended to be used with serializers.ModelSerializer subclasses.
 */
export interface DataWarehouseSavedQueryApi {
    readonly id: string
    /** @nullable */
    deleted?: boolean | null
    /** @maxLength 128 */
    name: string
    /** HogQL query */
    query?: unknown
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly sync_frequency: string
    readonly columns: string
    /** The status of when this SavedQuery last ran.

* `Cancelled` - Cancelled
* `Modified` - Modified
* `Completed` - Completed
* `Failed` - Failed
* `Running` - Running */
    readonly status: StatusD5cEnumApi | NullEnumApi
    /** @nullable */
    readonly last_run_at: string | null
    readonly managed_viewset_kind: string
    /** @nullable */
    readonly latest_error: string | null
    /** @nullable */
    edited_history_id?: string | null
    readonly latest_history_id: string
    /** @nullable */
    soft_update?: boolean | null
    /** @nullable */
    readonly is_materialized: boolean | null
    /** Where this SavedQuery is created.

* `data_warehouse` - Data Warehouse
* `endpoint` - Endpoint
* `managed_viewset` - Managed Viewset */
    readonly origin: OriginEnumApi | NullEnumApi
}

/**
 * Shared methods for DataWarehouseSavedQuery serializers.

This mixin is intended to be used with serializers.ModelSerializer subclasses.
 */
export interface PatchedDataWarehouseSavedQueryApi {
    readonly id?: string
    /** @nullable */
    deleted?: boolean | null
    /** @maxLength 128 */
    name?: string
    /** HogQL query */
    query?: unknown
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly sync_frequency?: string
    readonly columns?: string
    /** The status of when this SavedQuery last ran.

* `Cancelled` - Cancelled
* `Modified` - Modified
* `Completed` - Completed
* `Failed` - Failed
* `Running` - Running */
    readonly status?: StatusD5cEnumApi | NullEnumApi
    /** @nullable */
    readonly last_run_at?: string | null
    readonly managed_viewset_kind?: string
    /** @nullable */
    readonly latest_error?: string | null
    /** @nullable */
    edited_history_id?: string | null
    readonly latest_history_id?: string
    /** @nullable */
    soft_update?: boolean | null
    /** @nullable */
    readonly is_materialized?: boolean | null
    /** Where this SavedQuery is created.

* `data_warehouse` - Data Warehouse
* `endpoint` - Endpoint
* `managed_viewset` - Managed Viewset */
    readonly origin?: OriginEnumApi | NullEnumApi
}

export interface DataWarehouseSavedQueryDraftApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** HogQL query draft */
    query?: unknown
    /** @nullable */
    saved_query_id?: string | null
    /** @nullable */
    name?: string | null
    /**
     * view history id that the draft branched from
     * @maxLength 255
     * @nullable
     */
    edited_history_id?: string | null
}

export interface PaginatedDataWarehouseSavedQueryDraftListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataWarehouseSavedQueryDraftApi[]
}

export interface PatchedDataWarehouseSavedQueryDraftApi {
    readonly id?: string
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    /** HogQL query draft */
    query?: unknown
    /** @nullable */
    saved_query_id?: string | null
    /** @nullable */
    name?: string | null
    /**
     * view history id that the draft branched from
     * @maxLength 255
     * @nullable
     */
    edited_history_id?: string | null
}

export interface QueryTabStateApi {
    readonly id: string
    /** 
            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey
            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.
            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables
            for a user.
             */
    state?: unknown
}

export interface PaginatedQueryTabStateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: QueryTabStateApi[]
}

export interface PatchedQueryTabStateApi {
    readonly id?: string
    /** 
            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey
            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.
            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables
            for a user.
             */
    state?: unknown
}

export type EnvironmentsDataModelingJobsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * @nullable
     */
    saved_query_id?: string | null
}

export type EnvironmentsExternalDataSourcesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type EnvironmentsWarehouseSavedQueriesListParams = {
    /**
     * A page number within the paginated result set.
     */
    page?: number
    /**
     * A search term.
     */
    search?: string
}

export type EnvironmentsWarehouseSavedQueryDraftsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DataModelingJobsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * @nullable
     */
    saved_query_id?: string | null
}

export type ExternalDataSourcesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type QueryTabStateListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type WarehouseSavedQueriesListParams = {
    /**
     * A page number within the paginated result set.
     */
    page?: number
    /**
     * A search term.
     */
    search?: string
}
