/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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

/**
 * * `Cancelled` - Cancelled
 * `Completed` - Completed
 * `Failed` - Failed
 * `Running` - Running
 */
export type DataModelingJobStatusEnumApi =
    (typeof DataModelingJobStatusEnumApi)[keyof typeof DataModelingJobStatusEnumApi]

export const DataModelingJobStatusEnumApi = {
    Cancelled: 'Cancelled',
    Completed: 'Completed',
    Failed: 'Failed',
    Running: 'Running',
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

export interface CheckDatabaseNameResponseApi {
    name: string
    available: boolean
}

export interface DeprovisionWarehouseResponseApi {
    status: string
    team: string
}

export interface ProvisionWarehouseRequestApi {
    /** Name for the new database */
    database_name: string
}

export interface ProvisionWarehouseResponseApi {
    status: string
    team: string
}

export interface ResetPasswordResponseApi {
    username: string
    password: string
}

/**
 * * `pending` - pending
 * `provisioning` - provisioning
 * `ready` - ready
 * `failed` - failed
 * `deleting` - deleting
 * `deleted` - deleted
 */
export type WarehouseStatusResponseStateEnumApi =
    (typeof WarehouseStatusResponseStateEnumApi)[keyof typeof WarehouseStatusResponseStateEnumApi]

export const WarehouseStatusResponseStateEnumApi = {
    Pending: 'pending',
    Provisioning: 'provisioning',
    Ready: 'ready',
    Failed: 'failed',
    Deleting: 'deleting',
    Deleted: 'deleted',
} as const

export interface WarehouseStatusResponseApi {
    team_name: string
    state: WarehouseStatusResponseStateEnumApi
    status_message: string
    /** @nullable */
    ready_at: string | null
    /** @nullable */
    failed_at: string | null
}

export type SyncTypeEnumApi = (typeof SyncTypeEnumApi)[keyof typeof SyncTypeEnumApi]

export const SyncTypeEnumApi = {
    FullRefresh: 'full_refresh',
    Incremental: 'incremental',
    Append: 'append',
    Webhook: 'webhook',
    Cdc: 'cdc',
} as const

/**
 * * `consolidated` - consolidated
 * `cdc_only` - cdc_only
 * `both` - both
 */
export type CdcTableModeEnumApi = (typeof CdcTableModeEnumApi)[keyof typeof CdcTableModeEnumApi]

export const CdcTableModeEnumApi = {
    Consolidated: 'consolidated',
    CdcOnly: 'cdc_only',
    Both: 'both',
} as const

/**
 * @nullable
 */
export type ExternalDataSchemaApiTable = { [key: string]: unknown } | null | null

export interface ExternalDataSchemaApi {
    readonly id: string
    readonly name: string
    /** @nullable */
    readonly label: string | null
    /** @nullable */
    readonly table: ExternalDataSchemaApiTable
    should_sync?: boolean
    /** @nullable */
    readonly last_synced_at: string | null
    /**
     * The latest error that occurred when syncing this schema.
     * @nullable
     */
    readonly latest_error: string | null
    readonly incremental: boolean
    /** @nullable */
    readonly status: string | null
    readonly sync_type: SyncTypeEnumApi | null
    /** @nullable */
    readonly incremental_field: string | null
    /** @nullable */
    readonly incremental_field_type: string | null
    /** @nullable */
    readonly sync_frequency: string | null
    /** @nullable */
    readonly sync_time_of_day: string | null
    /** @nullable */
    readonly description: string | null
    /** @nullable */
    readonly primary_key_columns: readonly string[] | null
    readonly cdc_table_mode: CdcTableModeEnumApi
}

export interface PaginatedExternalDataSchemaListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSchemaApi[]
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
 * `Clerk` - Clerk
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
 * `Attio` - Attio
 * `SnapchatAds` - SnapchatAds
 * `Linear` - Linear
 * `Intercom` - Intercom
 * `Amplitude` - Amplitude
 * `Mixpanel` - Mixpanel
 * `Jira` - Jira
 * `ActiveCampaign` - ActiveCampaign
 * `Marketo` - Marketo
 * `Adjust` - Adjust
 * `AppsFlyer` - AppsFlyer
 * `Freshdesk` - Freshdesk
 * `GoogleAnalytics` - GoogleAnalytics
 * `Pipedrive` - Pipedrive
 * `SendGrid` - SendGrid
 * `Slack` - Slack
 * `PagerDuty` - PagerDuty
 * `Asana` - Asana
 * `Notion` - Notion
 * `Airtable` - Airtable
 * `Greenhouse` - Greenhouse
 * `BambooHR` - BambooHR
 * `Lever` - Lever
 * `GitLab` - GitLab
 * `Datadog` - Datadog
 * `Sentry` - Sentry
 * `Pendo` - Pendo
 * `FullStory` - FullStory
 * `AmazonAds` - AmazonAds
 * `PinterestAds` - PinterestAds
 * `AppleSearchAds` - AppleSearchAds
 * `QuickBooks` - QuickBooks
 * `Xero` - Xero
 * `NetSuite` - NetSuite
 * `WooCommerce` - WooCommerce
 * `BigCommerce` - BigCommerce
 * `PayPal` - PayPal
 * `Square` - Square
 * `Zoom` - Zoom
 * `Trello` - Trello
 * `Monday` - Monday
 * `ClickUp` - ClickUp
 * `Confluence` - Confluence
 * `Recurly` - Recurly
 * `SalesLoft` - SalesLoft
 * `Outreach` - Outreach
 * `Gong` - Gong
 * `Calendly` - Calendly
 * `Typeform` - Typeform
 * `Iterable` - Iterable
 * `ZohoCRM` - ZohoCRM
 * `Close` - Close
 * `Oracle` - Oracle
 * `DynamoDB` - DynamoDB
 * `Elasticsearch` - Elasticsearch
 * `Kafka` - Kafka
 * `LaunchDarkly` - LaunchDarkly
 * `Braintree` - Braintree
 * `Recharge` - Recharge
 * `HelpScout` - HelpScout
 * `Gorgias` - Gorgias
 * `Instagram` - Instagram
 * `YouTubeAnalytics` - YouTubeAnalytics
 * `FacebookPages` - FacebookPages
 * `TwitterAds` - TwitterAds
 * `Workday` - Workday
 * `ServiceNow` - ServiceNow
 * `Pardot` - Pardot
 * `Copper` - Copper
 * `Front` - Front
 * `ChartMogul` - ChartMogul
 * `Zuora` - Zuora
 * `Paddle` - Paddle
 * `CircleCI` - CircleCI
 * `CockroachDB` - CockroachDB
 * `Firebase` - Firebase
 * `AzureBlob` - AzureBlob
 * `GoogleDrive` - GoogleDrive
 * `OneDrive` - OneDrive
 * `SharePoint` - SharePoint
 * `Box` - Box
 * `SFTP` - SFTP
 * `MicrosoftTeams` - MicrosoftTeams
 * `Aircall` - Aircall
 * `Webflow` - Webflow
 * `Okta` - Okta
 * `Auth0` - Auth0
 * `Productboard` - Productboard
 * `Smartsheet` - Smartsheet
 * `Wrike` - Wrike
 * `Plaid` - Plaid
 * `SurveyMonkey` - SurveyMonkey
 * `Eventbrite` - Eventbrite
 * `RingCentral` - RingCentral
 * `Twilio` - Twilio
 * `Freshsales` - Freshsales
 * `Shortcut` - Shortcut
 * `ConvertKit` - ConvertKit
 * `Drip` - Drip
 * `CampaignMonitor` - CampaignMonitor
 * `MailerLite` - MailerLite
 * `Omnisend` - Omnisend
 * `Brevo` - Brevo
 * `Postmark` - Postmark
 * `Granola` - Granola
 * `BuildBetter` - BuildBetter
 * `Convex` - Convex
 * `ClickHouse` - ClickHouse
 */
export type SourceType9a7EnumApi = (typeof SourceType9a7EnumApi)[keyof typeof SourceType9a7EnumApi]

export const SourceType9a7EnumApi = {
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
    Mssql: 'MSSQL',
    Vitally: 'Vitally',
    BigQuery: 'BigQuery',
    Chargebee: 'Chargebee',
    Clerk: 'Clerk',
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
    Attio: 'Attio',
    SnapchatAds: 'SnapchatAds',
    Linear: 'Linear',
    Intercom: 'Intercom',
    Amplitude: 'Amplitude',
    Mixpanel: 'Mixpanel',
    Jira: 'Jira',
    ActiveCampaign: 'ActiveCampaign',
    Marketo: 'Marketo',
    Adjust: 'Adjust',
    AppsFlyer: 'AppsFlyer',
    Freshdesk: 'Freshdesk',
    GoogleAnalytics: 'GoogleAnalytics',
    Pipedrive: 'Pipedrive',
    SendGrid: 'SendGrid',
    Slack: 'Slack',
    PagerDuty: 'PagerDuty',
    Asana: 'Asana',
    Notion: 'Notion',
    Airtable: 'Airtable',
    Greenhouse: 'Greenhouse',
    BambooHR: 'BambooHR',
    Lever: 'Lever',
    GitLab: 'GitLab',
    Datadog: 'Datadog',
    Sentry: 'Sentry',
    Pendo: 'Pendo',
    FullStory: 'FullStory',
    AmazonAds: 'AmazonAds',
    PinterestAds: 'PinterestAds',
    AppleSearchAds: 'AppleSearchAds',
    QuickBooks: 'QuickBooks',
    Xero: 'Xero',
    NetSuite: 'NetSuite',
    WooCommerce: 'WooCommerce',
    BigCommerce: 'BigCommerce',
    PayPal: 'PayPal',
    Square: 'Square',
    Zoom: 'Zoom',
    Trello: 'Trello',
    Monday: 'Monday',
    ClickUp: 'ClickUp',
    Confluence: 'Confluence',
    Recurly: 'Recurly',
    SalesLoft: 'SalesLoft',
    Outreach: 'Outreach',
    Gong: 'Gong',
    Calendly: 'Calendly',
    Typeform: 'Typeform',
    Iterable: 'Iterable',
    ZohoCRM: 'ZohoCRM',
    Close: 'Close',
    Oracle: 'Oracle',
    DynamoDB: 'DynamoDB',
    Elasticsearch: 'Elasticsearch',
    Kafka: 'Kafka',
    LaunchDarkly: 'LaunchDarkly',
    Braintree: 'Braintree',
    Recharge: 'Recharge',
    HelpScout: 'HelpScout',
    Gorgias: 'Gorgias',
    Instagram: 'Instagram',
    YouTubeAnalytics: 'YouTubeAnalytics',
    FacebookPages: 'FacebookPages',
    TwitterAds: 'TwitterAds',
    Workday: 'Workday',
    ServiceNow: 'ServiceNow',
    Pardot: 'Pardot',
    Copper: 'Copper',
    Front: 'Front',
    ChartMogul: 'ChartMogul',
    Zuora: 'Zuora',
    Paddle: 'Paddle',
    CircleCI: 'CircleCI',
    CockroachDB: 'CockroachDB',
    Firebase: 'Firebase',
    AzureBlob: 'AzureBlob',
    GoogleDrive: 'GoogleDrive',
    OneDrive: 'OneDrive',
    SharePoint: 'SharePoint',
    Box: 'Box',
    Sftp: 'SFTP',
    MicrosoftTeams: 'MicrosoftTeams',
    Aircall: 'Aircall',
    Webflow: 'Webflow',
    Okta: 'Okta',
    Auth0: 'Auth0',
    Productboard: 'Productboard',
    Smartsheet: 'Smartsheet',
    Wrike: 'Wrike',
    Plaid: 'Plaid',
    SurveyMonkey: 'SurveyMonkey',
    Eventbrite: 'Eventbrite',
    RingCentral: 'RingCentral',
    Twilio: 'Twilio',
    Freshsales: 'Freshsales',
    Shortcut: 'Shortcut',
    ConvertKit: 'ConvertKit',
    Drip: 'Drip',
    CampaignMonitor: 'CampaignMonitor',
    MailerLite: 'MailerLite',
    Omnisend: 'Omnisend',
    Brevo: 'Brevo',
    Postmark: 'Postmark',
    Granola: 'Granola',
    BuildBetter: 'BuildBetter',
    Convex: 'Convex',
    ClickHouse: 'ClickHouse',
} as const

/**
 * * `warehouse` - warehouse
 * `direct` - direct
 */
export type AccessMethodEnumApi = (typeof AccessMethodEnumApi)[keyof typeof AccessMethodEnumApi]

export const AccessMethodEnumApi = {
    Warehouse: 'warehouse',
    Direct: 'direct',
} as const

/**
 * * `duckdb` - duckdb
 * `postgres` - postgres
 */
export type EngineEnumApi = (typeof EngineEnumApi)[keyof typeof EngineEnumApi]

export const EngineEnumApi = {
    Duckdb: 'duckdb',
    Postgres: 'postgres',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

export interface ExternalDataSourceRevenueAnalyticsConfigApi {
    enabled?: boolean
    include_invoiceless_charges?: boolean
}

export type ExternalDataSourceSerializersApiSchemasItem = { [key: string]: unknown }

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
    readonly source_type: SourceType9a7EnumApi
    /** @nullable */
    readonly latest_error: string | null
    /**
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly access_method: AccessMethodEnumApi
    /** Backend engine detected for the direct connection.

* `duckdb` - duckdb
* `postgres` - postgres */
    readonly engine: EngineEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_run_at: string | null
    readonly schemas: readonly ExternalDataSourceSerializersApiSchemasItem[]
    job_inputs?: unknown | null
    readonly revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly supports_webhooks: boolean
}

export interface PaginatedExternalDataSourceSerializersListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSourceSerializersApi[]
}

export type PatchedExternalDataSourceSerializersApiSchemasItem = { [key: string]: unknown }

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
    readonly source_type?: SourceType9a7EnumApi
    /** @nullable */
    readonly latest_error?: string | null
    /**
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly access_method?: AccessMethodEnumApi
    /** Backend engine detected for the direct connection.

* `duckdb` - duckdb
* `postgres` - postgres */
    readonly engine?: EngineEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_run_at?: string | null
    readonly schemas?: readonly PatchedExternalDataSourceSerializersApiSchemasItem[]
    job_inputs?: unknown | null
    readonly revenue_analytics_config?: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    readonly supports_webhooks?: boolean
}

export interface ExternalDataSourceBulkUpdateSchemaApi {
    /** Schema identifier to update. */
    id: string
    /** Whether the schema should be queryable/synced. */
    should_sync?: boolean
    /** Requested sync mode for the schema.

* `full_refresh` - full_refresh
* `incremental` - incremental
* `append` - append
* `webhook` - webhook
* `cdc` - cdc */
    sync_type?: SyncTypeEnumApi | NullEnumApi | null
    /**
     * Incremental cursor field for incremental or append syncs.
     * @nullable
     */
    incremental_field?: string | null
    /**
     * Type of the incremental cursor field.
     * @nullable
     */
    incremental_field_type?: string | null
    /**
     * Human-readable sync frequency value.
     * @nullable
     */
    sync_frequency?: string | null
    /**
     * UTC anchor time for scheduled syncs.
     * @nullable
     */
    sync_time_of_day?: string | null
    /** How CDC-backed tables should be exposed.

* `consolidated` - consolidated
* `cdc_only` - cdc_only
* `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | NullEnumApi | null
}

export interface PatchedExternalDataSourceBulkUpdateSchemasApi {
    /** Schema updates to apply in a single batch. */
    schemas?: ExternalDataSourceBulkUpdateSchemaApi[]
}

export interface ExternalDataSourceConnectionOptionApi {
    readonly id: string
    /** @nullable */
    readonly prefix: string | null
    /** Backend engine detected for the direct connection.

* `duckdb` - duckdb
* `postgres` - postgres */
    readonly engine: EngineEnumApi | NullEnumApi | null
}

export interface PaginatedExternalDataSourceConnectionOptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSourceConnectionOptionApi[]
}

export interface QueryTabStateApi {
    readonly id: string
    /**
            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey
            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.
            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables
            for a user.
             */
    state?: unknown | null
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
    state?: unknown | null
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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

export interface DataWarehouseModelPathApi {
    readonly id: string
    path: string
    team: number
    /** @nullable */
    table?: string | null
    /** @nullable */
    saved_query?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedDataWarehouseModelPathListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataWarehouseModelPathApi[]
}

/**
 * * `Cancelled` - Cancelled
 * `Modified` - Modified
 * `Completed` - Completed
 * `Failed` - Failed
 * `Running` - Running
 */
export type StatusD5cEnumApi = (typeof StatusD5cEnumApi)[keyof typeof StatusD5cEnumApi]

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

export const OriginEnumApi = {
    DataWarehouse: 'data_warehouse',
    Endpoint: 'endpoint',
    ManagedViewset: 'managed_viewset',
} as const

export type DataWarehouseSavedQueryMinimalApiColumnsItem = { [key: string]: unknown }

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
    /** @nullable */
    readonly sync_frequency: string | null
    readonly columns: readonly DataWarehouseSavedQueryMinimalApiColumnsItem[]
    /** The status of when this SavedQuery last ran.

* `Cancelled` - Cancelled
* `Modified` - Modified
* `Completed` - Completed
* `Failed` - Failed
* `Running` - Running */
    readonly status: StatusD5cEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_run_at: string | null
    /** @nullable */
    readonly managed_viewset_kind: string | null
    /** @nullable */
    readonly folder_id: string | null
    /** @nullable */
    readonly folder_name: string | null
    /** @nullable */
    readonly latest_error: string | null
    /** @nullable */
    readonly is_materialized: boolean | null
    /** Where this SavedQuery is created.

* `data_warehouse` - Data Warehouse
* `endpoint` - Endpoint
* `managed_viewset` - Managed Viewset */
    readonly origin: OriginEnumApi | NullEnumApi | null
    /** Whether this view is for testing only and will auto-expire. */
    readonly is_test: boolean
    /**
     * When this test view should be automatically deleted.
     * @nullable
     */
    readonly expires_at: string | null
}

export interface PaginatedDataWarehouseSavedQueryMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataWarehouseSavedQueryMinimalApi[]
}

export type DataWarehouseSavedQueryApiColumnsItem = { [key: string]: unknown }

/**
 * Shared methods for DataWarehouseSavedQuery serializers.

This mixin is intended to be used with serializers.ModelSerializer subclasses.
 */
export interface DataWarehouseSavedQueryApi {
    readonly id: string
    /** @nullable */
    deleted?: boolean | null
    /**
     * Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.
     * @maxLength 128
     */
    name: string
    /** HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"} */
    query?: unknown | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly sync_frequency: string | null
    readonly columns: readonly DataWarehouseSavedQueryApiColumnsItem[]
    /** The status of when this SavedQuery last ran.

* `Cancelled` - Cancelled
* `Modified` - Modified
* `Completed` - Completed
* `Failed` - Failed
* `Running` - Running */
    readonly status: StatusD5cEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_run_at: string | null
    /** @nullable */
    readonly managed_viewset_kind: string | null
    /**
     * Optional folder ID used to organize this view in the SQL editor sidebar.
     * @nullable
     */
    folder_id?: string | null
    /**
     * Folder name used to organize this view in the SQL editor sidebar.
     * @nullable
     */
    readonly folder_name: string | null
    /** @nullable */
    readonly latest_error: string | null
    /**
     * Activity log ID from the last known edit. Used for conflict detection.
     * @nullable
     */
    edited_history_id?: string | null
    /** @nullable */
    readonly latest_history_id: number | null
    /**
     * If true, skip column inference and validation. For saving drafts.
     * @nullable
     */
    soft_update?: boolean | null
    /**
     * Optional DAG to place this view into
     * @nullable
     */
    dag_id?: string | null
    /** @nullable */
    readonly is_materialized: boolean | null
    /** Where this SavedQuery is created.

* `data_warehouse` - Data Warehouse
* `endpoint` - Endpoint
* `managed_viewset` - Managed Viewset */
    readonly origin: OriginEnumApi | NullEnumApi | null
    /** Whether this view is for testing only and will auto-expire. */
    is_test?: boolean
    /**
     * When this test view should be automatically deleted.
     * @nullable
     */
    readonly expires_at: string | null
}

export type PatchedDataWarehouseSavedQueryApiColumnsItem = { [key: string]: unknown }

/**
 * Shared methods for DataWarehouseSavedQuery serializers.

This mixin is intended to be used with serializers.ModelSerializer subclasses.
 */
export interface PatchedDataWarehouseSavedQueryApi {
    readonly id?: string
    /** @nullable */
    deleted?: boolean | null
    /**
     * Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.
     * @maxLength 128
     */
    name?: string
    /** HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"} */
    query?: unknown | null
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @nullable */
    readonly sync_frequency?: string | null
    readonly columns?: readonly PatchedDataWarehouseSavedQueryApiColumnsItem[]
    /** The status of when this SavedQuery last ran.

* `Cancelled` - Cancelled
* `Modified` - Modified
* `Completed` - Completed
* `Failed` - Failed
* `Running` - Running */
    readonly status?: StatusD5cEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_run_at?: string | null
    /** @nullable */
    readonly managed_viewset_kind?: string | null
    /**
     * Optional folder ID used to organize this view in the SQL editor sidebar.
     * @nullable
     */
    folder_id?: string | null
    /**
     * Folder name used to organize this view in the SQL editor sidebar.
     * @nullable
     */
    readonly folder_name?: string | null
    /** @nullable */
    readonly latest_error?: string | null
    /**
     * Activity log ID from the last known edit. Used for conflict detection.
     * @nullable
     */
    edited_history_id?: string | null
    /** @nullable */
    readonly latest_history_id?: number | null
    /**
     * If true, skip column inference and validation. For saving drafts.
     * @nullable
     */
    soft_update?: boolean | null
    /**
     * Optional DAG to place this view into
     * @nullable
     */
    dag_id?: string | null
    /** @nullable */
    readonly is_materialized?: boolean | null
    /** Where this SavedQuery is created.

* `data_warehouse` - Data Warehouse
* `endpoint` - Endpoint
* `managed_viewset` - Managed Viewset */
    readonly origin?: OriginEnumApi | NullEnumApi | null
    /** Whether this view is for testing only and will auto-expire. */
    is_test?: boolean
    /**
     * When this test view should be automatically deleted.
     * @nullable
     */
    readonly expires_at?: string | null
}

export interface DataWarehouseSavedQueryFolderApi {
    readonly id: string
    /**
     * Display name for the folder used to organize saved queries in the SQL editor sidebar.
     * @maxLength 128
     */
    name: string
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly view_count: number
}

export interface PatchedDataWarehouseSavedQueryFolderApi {
    readonly id?: string
    /**
     * Display name for the folder used to organize saved queries in the SQL editor sidebar.
     * @maxLength 128
     */
    name?: string
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly view_count?: number
}

/**
 * * `CSV` - CSV
 * `CSVWithNames` - CSVWithNames
 * `Parquet` - Parquet
 * `JSONEachRow` - JSON
 * `Delta` - Delta
 * `DeltaS3Wrapper` - DeltaS3Wrapper
 */
export type TableFormatEnumApi = (typeof TableFormatEnumApi)[keyof typeof TableFormatEnumApi]

export const TableFormatEnumApi = {
    Csv: 'CSV',
    CSVWithNames: 'CSVWithNames',
    Parquet: 'Parquet',
    JSONEachRow: 'JSONEachRow',
    Delta: 'Delta',
    DeltaS3Wrapper: 'DeltaS3Wrapper',
} as const

export interface CredentialApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @maxLength 500 */
    access_key: string
    /** @maxLength 500 */
    access_secret: string
}

export interface SimpleExternalDataSourceSerializersApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    readonly status: string
    readonly source_type: SourceType9a7EnumApi
}

export type TableApiColumnsItem = { [key: string]: unknown }

/**
 * @nullable
 */
export type TableApiExternalSchema = { [key: string]: unknown } | null | null

export type TableApiOptions = { [key: string]: unknown }

export interface TableApi {
    readonly id: string
    /** @nullable */
    deleted?: boolean | null
    /** @maxLength 128 */
    name: string
    format: TableFormatEnumApi
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @maxLength 500 */
    url_pattern: string
    credential: CredentialApi
    readonly columns: readonly TableApiColumnsItem[]
    readonly external_data_source: SimpleExternalDataSourceSerializersApi
    /** @nullable */
    readonly external_schema: TableApiExternalSchema
    options?: TableApiOptions
}

export interface PaginatedTableListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TableApi[]
}

export interface ViewLinkApi {
    readonly id: string
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @maxLength 400 */
    source_table_name: string
    /** @maxLength 400 */
    source_table_key: string
    /** @maxLength 400 */
    joining_table_name: string
    /** @maxLength 400 */
    joining_table_key: string
    /** @maxLength 400 */
    field_name: string
    configuration?: unknown | null
}

export interface PaginatedViewLinkListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ViewLinkApi[]
}

export interface ViewLinkValidationApi {
    /** @maxLength 255 */
    joining_table_name: string
    /** @maxLength 255 */
    joining_table_key: string
    /** @maxLength 255 */
    source_table_name: string
    /** @maxLength 255 */
    source_table_key: string
}

export type WarehouseSavedQueryDraftsListParams = {
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

export type DataWarehouseCheckDatabaseNameRetrieveParams = {
    /**
     * Database name to check
     * @minLength 1
     */
    name: string
}

export type ExternalDataSchemasListParams = {
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

export type ExternalDataSourcesBulkUpdateSchemasPartialUpdateParams = {
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

export type ExternalDataSourcesCheckCdcPrerequisitesCreate200 = {
    valid?: boolean
    errors?: string[]
}

export type ExternalDataSourcesConnectionsListParams = {
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

export type WarehouseModelPathsListParams = {
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

export type WarehouseTablesListParams = {
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

export type WarehouseViewLinkListParams = {
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

export type WarehouseViewLinksListParams = {
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
