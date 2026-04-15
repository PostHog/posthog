/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const warehouseSavedQueryDraftsListResponseResultsItemEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            query: zod.unknown().optional().describe('HogQL query draft'),
            saved_query_id: zod.uuid().nullish(),
            name: zod.string().nullish(),
            edited_history_id: zod
                .string()
                .max(warehouseSavedQueryDraftsListResponseResultsItemEditedHistoryIdMax)
                .nullish()
                .describe('view history id that the draft branched from'),
        })
    ),
})

export const warehouseSavedQueryDraftsCreateBodyEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsCreateBody = /* @__PURE__ */ zod.object({
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.uuid().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsCreateBodyEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsRetrieveResponseEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.uuid().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsRetrieveResponseEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsUpdateBodyEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsUpdateBody = /* @__PURE__ */ zod.object({
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.uuid().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsUpdateBodyEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsUpdateResponseEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.uuid().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsUpdateResponseEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsPartialUpdateBodyEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsPartialUpdateBody = /* @__PURE__ */ zod.object({
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.uuid().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsPartialUpdateBodyEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsPartialUpdateResponseEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.uuid().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsPartialUpdateResponseEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const DataModelingJobsListResponse = /* @__PURE__ */ zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            saved_query_id: zod.uuid().nullable(),
            status: zod
                .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
                .describe(
                    '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                ),
            rows_materialized: zod.number(),
            error: zod.string().nullable(),
            created_at: zod.iso.datetime({}),
            last_run_at: zod.iso.datetime({}),
            workflow_id: zod.string().nullable(),
            workflow_run_id: zod.string().nullable(),
            rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
        })
    ),
})

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const DataModelingJobsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    saved_query_id: zod.uuid().nullable(),
    status: zod
        .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
        .describe('* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'),
    rows_materialized: zod.number(),
    error: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    last_run_at: zod.iso.datetime({}),
    workflow_id: zod.string().nullable(),
    workflow_run_id: zod.string().nullable(),
    rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
})

/**
 * Get the most recent non-running job for each saved query from the v2 backend.
 */
export const DataModelingJobsRecentRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    saved_query_id: zod.uuid().nullable(),
    status: zod
        .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
        .describe('* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'),
    rows_materialized: zod.number(),
    error: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    last_run_at: zod.iso.datetime({}),
    workflow_id: zod.string().nullable(),
    workflow_run_id: zod.string().nullable(),
    rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
})

/**
 * Get all currently running jobs from the v2 backend.
 */
export const DataModelingJobsRunningRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    saved_query_id: zod.uuid().nullable(),
    status: zod
        .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
        .describe('* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'),
    rows_materialized: zod.number(),
    error: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    last_run_at: zod.iso.datetime({}),
    workflow_id: zod.string().nullable(),
    workflow_run_id: zod.string().nullable(),
    rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
})

/**
 * Check if a database name is available.
 */
export const DataWarehouseCheckDatabaseNameRetrieveResponse = /* @__PURE__ */ zod.object({
    name: zod.string(),
    available: zod.boolean(),
})

/**
 * Start deprovisioning the managed warehouse for this team.
 */
export const DataWarehouseDeprovisionCreateResponse = /* @__PURE__ */ zod.object({
    status: zod.string(),
    team: zod.string(),
})

/**
 * Start provisioning a managed warehouse for this team.
 */
export const DataWarehouseProvisionCreateBody = /* @__PURE__ */ zod.object({
    database_name: zod.string().describe('Name for the new database'),
})

export const DataWarehouseProvisionCreateResponse = /* @__PURE__ */ zod.object({
    status: zod.string(),
    team: zod.string(),
})

/**
 * Reset the root password for the managed warehouse.
 */
export const DataWarehouseResetPasswordCreateResponse = /* @__PURE__ */ zod.object({
    username: zod.string(),
    password: zod.string(),
})

/**
 * Get the current provisioning status of the managed warehouse.
 */
export const DataWarehouseWarehouseStatusRetrieveResponse = /* @__PURE__ */ zod.object({
    team_name: zod.string(),
    state: zod
        .enum(['pending', 'provisioning', 'ready', 'failed', 'deleting', 'deleted'])
        .describe(
            '* `pending` - pending\n* `provisioning` - provisioning\n* `ready` - ready\n* `failed` - failed\n* `deleting` - deleting\n* `deleted` - deleted'
        ),
    status_message: zod.string(),
    ready_at: zod.iso.datetime({}).nullable(),
    failed_at: zod.iso.datetime({}).nullable(),
})

export const ExternalDataSchemasListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string(),
            label: zod.string().nullable(),
            table: zod.record(zod.string(), zod.unknown()).nullable(),
            should_sync: zod.boolean().optional(),
            last_synced_at: zod.iso.datetime({}).nullable(),
            latest_error: zod.string().nullable().describe('The latest error that occurred when syncing this schema.'),
            incremental: zod.boolean(),
            status: zod.string().nullable(),
            sync_type: zod.enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc']).nullable(),
            incremental_field: zod.string().nullable(),
            incremental_field_type: zod.string().nullable(),
            sync_frequency: zod.string().nullable(),
            sync_time_of_day: zod.iso.time({}).nullable(),
            description: zod.string().nullable(),
            primary_key_columns: zod.array(zod.string()).nullable(),
            cdc_table_mode: zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
        })
    ),
})

export const ExternalDataSchemasCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesListResponseResultsItemPrefixMax = 100

export const externalDataSourcesListResponseResultsItemDescriptionMax = 400

export const ExternalDataSourcesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                created_at: zod.iso.datetime({}),
                created_by: zod.string().nullable(),
                status: zod.string(),
                client_secret: zod.string(),
                account_id: zod.string(),
                source_type: zod
                    .enum([
                        'Ashby',
                        'Supabase',
                        'CustomerIO',
                        'Github',
                        'Stripe',
                        'Hubspot',
                        'Postgres',
                        'Zendesk',
                        'Snowflake',
                        'Salesforce',
                        'MySQL',
                        'MongoDB',
                        'MSSQL',
                        'Vitally',
                        'BigQuery',
                        'Chargebee',
                        'Clerk',
                        'GoogleAds',
                        'TemporalIO',
                        'DoIt',
                        'GoogleSheets',
                        'MetaAds',
                        'Klaviyo',
                        'Mailchimp',
                        'Braze',
                        'Mailjet',
                        'Redshift',
                        'Polar',
                        'RevenueCat',
                        'LinkedinAds',
                        'RedditAds',
                        'TikTokAds',
                        'BingAds',
                        'Shopify',
                        'Attio',
                        'SnapchatAds',
                        'Linear',
                        'Intercom',
                        'Amplitude',
                        'Mixpanel',
                        'Jira',
                        'ActiveCampaign',
                        'Marketo',
                        'Adjust',
                        'AppsFlyer',
                        'Freshdesk',
                        'GoogleAnalytics',
                        'Pipedrive',
                        'SendGrid',
                        'Slack',
                        'PagerDuty',
                        'Asana',
                        'Notion',
                        'Airtable',
                        'Greenhouse',
                        'BambooHR',
                        'Lever',
                        'GitLab',
                        'Datadog',
                        'Sentry',
                        'Pendo',
                        'FullStory',
                        'AmazonAds',
                        'PinterestAds',
                        'AppleSearchAds',
                        'QuickBooks',
                        'Xero',
                        'NetSuite',
                        'WooCommerce',
                        'BigCommerce',
                        'PayPal',
                        'Square',
                        'Zoom',
                        'Trello',
                        'Monday',
                        'ClickUp',
                        'Confluence',
                        'Recurly',
                        'SalesLoft',
                        'Outreach',
                        'Gong',
                        'Calendly',
                        'Typeform',
                        'Iterable',
                        'ZohoCRM',
                        'Close',
                        'Oracle',
                        'DynamoDB',
                        'Elasticsearch',
                        'Kafka',
                        'LaunchDarkly',
                        'Braintree',
                        'Recharge',
                        'HelpScout',
                        'Gorgias',
                        'Instagram',
                        'YouTubeAnalytics',
                        'FacebookPages',
                        'TwitterAds',
                        'Workday',
                        'ServiceNow',
                        'Pardot',
                        'Copper',
                        'Front',
                        'ChartMogul',
                        'Zuora',
                        'Paddle',
                        'CircleCI',
                        'CockroachDB',
                        'Firebase',
                        'AzureBlob',
                        'GoogleDrive',
                        'OneDrive',
                        'SharePoint',
                        'Box',
                        'SFTP',
                        'MicrosoftTeams',
                        'Aircall',
                        'Webflow',
                        'Okta',
                        'Auth0',
                        'Productboard',
                        'Smartsheet',
                        'Wrike',
                        'Plaid',
                        'SurveyMonkey',
                        'Eventbrite',
                        'RingCentral',
                        'Twilio',
                        'Freshsales',
                        'Shortcut',
                        'ConvertKit',
                        'Drip',
                        'CampaignMonitor',
                        'MailerLite',
                        'Omnisend',
                        'Brevo',
                        'Postmark',
                        'Granola',
                        'BuildBetter',
                        'Convex',
                    ])
                    .describe(
                        '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex'
                    ),
                latest_error: zod.string().nullable(),
                prefix: zod.string().max(externalDataSourcesListResponseResultsItemPrefixMax).nullish(),
                description: zod.string().max(externalDataSourcesListResponseResultsItemDescriptionMax).nullish(),
                access_method: zod
                    .enum(['warehouse', 'direct'])
                    .describe('* `warehouse` - warehouse\n* `direct` - direct'),
                engine: zod
                    .union([
                        zod.enum(['duckdb', 'postgres']).describe('* `duckdb` - duckdb\n* `postgres` - postgres'),
                        zod.literal(null),
                    ])
                    .nullable()
                    .describe(
                        'Backend engine detected for the direct connection.\n\n* `duckdb` - duckdb\n* `postgres` - postgres'
                    ),
                last_run_at: zod.string(),
                schemas: zod.array(zod.record(zod.string(), zod.unknown())),
                job_inputs: zod.unknown().nullish(),
                revenue_analytics_config: zod.object({
                    enabled: zod.boolean().optional(),
                    include_invoiceless_charges: zod.boolean().optional(),
                }),
                user_access_level: zod
                    .string()
                    .nullable()
                    .describe('The effective access level the user has for this object'),
                supports_webhooks: zod.boolean(),
            })
            .describe('Mixin for serializers to add user access control fields')
    ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesRetrieveResponsePrefixMax = 100

export const externalDataSourcesRetrieveResponseDescriptionMax = 400

export const ExternalDataSourcesRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        created_at: zod.iso.datetime({}),
        created_by: zod.string().nullable(),
        status: zod.string(),
        client_secret: zod.string(),
        account_id: zod.string(),
        source_type: zod
            .enum([
                'Ashby',
                'Supabase',
                'CustomerIO',
                'Github',
                'Stripe',
                'Hubspot',
                'Postgres',
                'Zendesk',
                'Snowflake',
                'Salesforce',
                'MySQL',
                'MongoDB',
                'MSSQL',
                'Vitally',
                'BigQuery',
                'Chargebee',
                'Clerk',
                'GoogleAds',
                'TemporalIO',
                'DoIt',
                'GoogleSheets',
                'MetaAds',
                'Klaviyo',
                'Mailchimp',
                'Braze',
                'Mailjet',
                'Redshift',
                'Polar',
                'RevenueCat',
                'LinkedinAds',
                'RedditAds',
                'TikTokAds',
                'BingAds',
                'Shopify',
                'Attio',
                'SnapchatAds',
                'Linear',
                'Intercom',
                'Amplitude',
                'Mixpanel',
                'Jira',
                'ActiveCampaign',
                'Marketo',
                'Adjust',
                'AppsFlyer',
                'Freshdesk',
                'GoogleAnalytics',
                'Pipedrive',
                'SendGrid',
                'Slack',
                'PagerDuty',
                'Asana',
                'Notion',
                'Airtable',
                'Greenhouse',
                'BambooHR',
                'Lever',
                'GitLab',
                'Datadog',
                'Sentry',
                'Pendo',
                'FullStory',
                'AmazonAds',
                'PinterestAds',
                'AppleSearchAds',
                'QuickBooks',
                'Xero',
                'NetSuite',
                'WooCommerce',
                'BigCommerce',
                'PayPal',
                'Square',
                'Zoom',
                'Trello',
                'Monday',
                'ClickUp',
                'Confluence',
                'Recurly',
                'SalesLoft',
                'Outreach',
                'Gong',
                'Calendly',
                'Typeform',
                'Iterable',
                'ZohoCRM',
                'Close',
                'Oracle',
                'DynamoDB',
                'Elasticsearch',
                'Kafka',
                'LaunchDarkly',
                'Braintree',
                'Recharge',
                'HelpScout',
                'Gorgias',
                'Instagram',
                'YouTubeAnalytics',
                'FacebookPages',
                'TwitterAds',
                'Workday',
                'ServiceNow',
                'Pardot',
                'Copper',
                'Front',
                'ChartMogul',
                'Zuora',
                'Paddle',
                'CircleCI',
                'CockroachDB',
                'Firebase',
                'AzureBlob',
                'GoogleDrive',
                'OneDrive',
                'SharePoint',
                'Box',
                'SFTP',
                'MicrosoftTeams',
                'Aircall',
                'Webflow',
                'Okta',
                'Auth0',
                'Productboard',
                'Smartsheet',
                'Wrike',
                'Plaid',
                'SurveyMonkey',
                'Eventbrite',
                'RingCentral',
                'Twilio',
                'Freshsales',
                'Shortcut',
                'ConvertKit',
                'Drip',
                'CampaignMonitor',
                'MailerLite',
                'Omnisend',
                'Brevo',
                'Postmark',
                'Granola',
                'BuildBetter',
                'Convex',
            ])
            .describe(
                '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex'
            ),
        latest_error: zod.string().nullable(),
        prefix: zod.string().max(externalDataSourcesRetrieveResponsePrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRetrieveResponseDescriptionMax).nullish(),
        access_method: zod.enum(['warehouse', 'direct']).describe('* `warehouse` - warehouse\n* `direct` - direct'),
        engine: zod
            .union([
                zod.enum(['duckdb', 'postgres']).describe('* `duckdb` - duckdb\n* `postgres` - postgres'),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Backend engine detected for the direct connection.\n\n* `duckdb` - duckdb\n* `postgres` - postgres'
            ),
        last_run_at: zod.string(),
        schemas: zod.array(zod.record(zod.string(), zod.unknown())),
        job_inputs: zod.unknown().nullish(),
        revenue_analytics_config: zod.object({
            enabled: zod.boolean().optional(),
            include_invoiceless_charges: zod.boolean().optional(),
        }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        supports_webhooks: zod.boolean(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateBodyPrefixMax = 100

export const externalDataSourcesUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const externalDataSourcesUpdateResponsePrefixMax = 100

export const externalDataSourcesUpdateResponseDescriptionMax = 400

export const ExternalDataSourcesUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        created_at: zod.iso.datetime({}),
        created_by: zod.string().nullable(),
        status: zod.string(),
        client_secret: zod.string(),
        account_id: zod.string(),
        source_type: zod
            .enum([
                'Ashby',
                'Supabase',
                'CustomerIO',
                'Github',
                'Stripe',
                'Hubspot',
                'Postgres',
                'Zendesk',
                'Snowflake',
                'Salesforce',
                'MySQL',
                'MongoDB',
                'MSSQL',
                'Vitally',
                'BigQuery',
                'Chargebee',
                'Clerk',
                'GoogleAds',
                'TemporalIO',
                'DoIt',
                'GoogleSheets',
                'MetaAds',
                'Klaviyo',
                'Mailchimp',
                'Braze',
                'Mailjet',
                'Redshift',
                'Polar',
                'RevenueCat',
                'LinkedinAds',
                'RedditAds',
                'TikTokAds',
                'BingAds',
                'Shopify',
                'Attio',
                'SnapchatAds',
                'Linear',
                'Intercom',
                'Amplitude',
                'Mixpanel',
                'Jira',
                'ActiveCampaign',
                'Marketo',
                'Adjust',
                'AppsFlyer',
                'Freshdesk',
                'GoogleAnalytics',
                'Pipedrive',
                'SendGrid',
                'Slack',
                'PagerDuty',
                'Asana',
                'Notion',
                'Airtable',
                'Greenhouse',
                'BambooHR',
                'Lever',
                'GitLab',
                'Datadog',
                'Sentry',
                'Pendo',
                'FullStory',
                'AmazonAds',
                'PinterestAds',
                'AppleSearchAds',
                'QuickBooks',
                'Xero',
                'NetSuite',
                'WooCommerce',
                'BigCommerce',
                'PayPal',
                'Square',
                'Zoom',
                'Trello',
                'Monday',
                'ClickUp',
                'Confluence',
                'Recurly',
                'SalesLoft',
                'Outreach',
                'Gong',
                'Calendly',
                'Typeform',
                'Iterable',
                'ZohoCRM',
                'Close',
                'Oracle',
                'DynamoDB',
                'Elasticsearch',
                'Kafka',
                'LaunchDarkly',
                'Braintree',
                'Recharge',
                'HelpScout',
                'Gorgias',
                'Instagram',
                'YouTubeAnalytics',
                'FacebookPages',
                'TwitterAds',
                'Workday',
                'ServiceNow',
                'Pardot',
                'Copper',
                'Front',
                'ChartMogul',
                'Zuora',
                'Paddle',
                'CircleCI',
                'CockroachDB',
                'Firebase',
                'AzureBlob',
                'GoogleDrive',
                'OneDrive',
                'SharePoint',
                'Box',
                'SFTP',
                'MicrosoftTeams',
                'Aircall',
                'Webflow',
                'Okta',
                'Auth0',
                'Productboard',
                'Smartsheet',
                'Wrike',
                'Plaid',
                'SurveyMonkey',
                'Eventbrite',
                'RingCentral',
                'Twilio',
                'Freshsales',
                'Shortcut',
                'ConvertKit',
                'Drip',
                'CampaignMonitor',
                'MailerLite',
                'Omnisend',
                'Brevo',
                'Postmark',
                'Granola',
                'BuildBetter',
                'Convex',
            ])
            .describe(
                '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex'
            ),
        latest_error: zod.string().nullable(),
        prefix: zod.string().max(externalDataSourcesUpdateResponsePrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateResponseDescriptionMax).nullish(),
        access_method: zod.enum(['warehouse', 'direct']).describe('* `warehouse` - warehouse\n* `direct` - direct'),
        engine: zod
            .union([
                zod.enum(['duckdb', 'postgres']).describe('* `duckdb` - duckdb\n* `postgres` - postgres'),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Backend engine detected for the direct connection.\n\n* `duckdb` - duckdb\n* `postgres` - postgres'
            ),
        last_run_at: zod.string(),
        schemas: zod.array(zod.record(zod.string(), zod.unknown())),
        job_inputs: zod.unknown().nullish(),
        revenue_analytics_config: zod.object({
            enabled: zod.boolean().optional(),
            include_invoiceless_charges: zod.boolean().optional(),
        }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        supports_webhooks: zod.boolean(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const externalDataSourcesPartialUpdateResponsePrefixMax = 100

export const externalDataSourcesPartialUpdateResponseDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        created_at: zod.iso.datetime({}),
        created_by: zod.string().nullable(),
        status: zod.string(),
        client_secret: zod.string(),
        account_id: zod.string(),
        source_type: zod
            .enum([
                'Ashby',
                'Supabase',
                'CustomerIO',
                'Github',
                'Stripe',
                'Hubspot',
                'Postgres',
                'Zendesk',
                'Snowflake',
                'Salesforce',
                'MySQL',
                'MongoDB',
                'MSSQL',
                'Vitally',
                'BigQuery',
                'Chargebee',
                'Clerk',
                'GoogleAds',
                'TemporalIO',
                'DoIt',
                'GoogleSheets',
                'MetaAds',
                'Klaviyo',
                'Mailchimp',
                'Braze',
                'Mailjet',
                'Redshift',
                'Polar',
                'RevenueCat',
                'LinkedinAds',
                'RedditAds',
                'TikTokAds',
                'BingAds',
                'Shopify',
                'Attio',
                'SnapchatAds',
                'Linear',
                'Intercom',
                'Amplitude',
                'Mixpanel',
                'Jira',
                'ActiveCampaign',
                'Marketo',
                'Adjust',
                'AppsFlyer',
                'Freshdesk',
                'GoogleAnalytics',
                'Pipedrive',
                'SendGrid',
                'Slack',
                'PagerDuty',
                'Asana',
                'Notion',
                'Airtable',
                'Greenhouse',
                'BambooHR',
                'Lever',
                'GitLab',
                'Datadog',
                'Sentry',
                'Pendo',
                'FullStory',
                'AmazonAds',
                'PinterestAds',
                'AppleSearchAds',
                'QuickBooks',
                'Xero',
                'NetSuite',
                'WooCommerce',
                'BigCommerce',
                'PayPal',
                'Square',
                'Zoom',
                'Trello',
                'Monday',
                'ClickUp',
                'Confluence',
                'Recurly',
                'SalesLoft',
                'Outreach',
                'Gong',
                'Calendly',
                'Typeform',
                'Iterable',
                'ZohoCRM',
                'Close',
                'Oracle',
                'DynamoDB',
                'Elasticsearch',
                'Kafka',
                'LaunchDarkly',
                'Braintree',
                'Recharge',
                'HelpScout',
                'Gorgias',
                'Instagram',
                'YouTubeAnalytics',
                'FacebookPages',
                'TwitterAds',
                'Workday',
                'ServiceNow',
                'Pardot',
                'Copper',
                'Front',
                'ChartMogul',
                'Zuora',
                'Paddle',
                'CircleCI',
                'CockroachDB',
                'Firebase',
                'AzureBlob',
                'GoogleDrive',
                'OneDrive',
                'SharePoint',
                'Box',
                'SFTP',
                'MicrosoftTeams',
                'Aircall',
                'Webflow',
                'Okta',
                'Auth0',
                'Productboard',
                'Smartsheet',
                'Wrike',
                'Plaid',
                'SurveyMonkey',
                'Eventbrite',
                'RingCentral',
                'Twilio',
                'Freshsales',
                'Shortcut',
                'ConvertKit',
                'Drip',
                'CampaignMonitor',
                'MailerLite',
                'Omnisend',
                'Brevo',
                'Postmark',
                'Granola',
                'BuildBetter',
                'Convex',
            ])
            .describe(
                '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex'
            ),
        latest_error: zod.string().nullable(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateResponsePrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateResponseDescriptionMax).nullish(),
        access_method: zod.enum(['warehouse', 'direct']).describe('* `warehouse` - warehouse\n* `direct` - direct'),
        engine: zod
            .union([
                zod.enum(['duckdb', 'postgres']).describe('* `duckdb` - duckdb\n* `postgres` - postgres'),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Backend engine detected for the direct connection.\n\n* `duckdb` - duckdb\n* `postgres` - postgres'
            ),
        last_run_at: zod.string(),
        schemas: zod.array(zod.record(zod.string(), zod.unknown())),
        job_inputs: zod.unknown().nullish(),
        revenue_analytics_config: zod.object({
            enabled: zod.boolean().optional(),
            include_invoiceless_charges: zod.boolean().optional(),
        }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        supports_webhooks: zod.boolean(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const externalDataSourcesRefreshSchemasCreateBodyPrefixMax = 100

export const externalDataSourcesRefreshSchemasCreateBodyDescriptionMax = 400

export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesReloadCreateBodyPrefixMax = 100

export const externalDataSourcesReloadCreateBodyDescriptionMax = 400

export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesReloadCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesReloadCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax)
            .nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesConnectionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            prefix: zod.string().nullable(),
            engine: zod
                .union([
                    zod.enum(['duckdb', 'postgres']).describe('* `duckdb` - duckdb\n* `postgres` - postgres'),
                    zod.literal(null),
                ])
                .nullable()
                .describe(
                    'Backend engine detected for the direct connection.\n\n* `duckdb` - duckdb\n* `postgres` - postgres'
                ),
        })
    ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDatabaseSchemaCreateBodyPrefixMax = 100

export const externalDataSourcesDatabaseSchemaCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDatabaseSchemaCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDatabaseSchemaCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDatabaseSchemaCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesSourcePrefixCreateBodyPrefixMax = 100

export const externalDataSourcesSourcePrefixCreateBodyDescriptionMax = 400

export const ExternalDataSourcesSourcePrefixCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesSourcePrefixCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesSourcePrefixCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            state: zod
                .unknown()
                .nullish()
                .describe(
                    '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
                ),
        })
    ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateUpdateBody = /* @__PURE__ */ zod.object({
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

export const QueryTabStateUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStatePartialUpdateBody = /* @__PURE__ */ zod.object({
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

export const QueryTabStatePartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateUserRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

export const warehouseModelPathsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseModelPathsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseModelPathsListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseModelPathsListResponseResultsItemCreatedByOneEmailMax = 254

export const WarehouseModelPathsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            path: zod.string(),
            team: zod.number(),
            table: zod.uuid().nullish(),
            saved_query: zod.uuid().nullish(),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseModelPathsListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseModelPathsListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(warehouseModelPathsListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(warehouseModelPathsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                deleted: zod.boolean().nullable(),
                name: zod.string(),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(warehouseSavedQueriesListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(warehouseSavedQueriesListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(warehouseSavedQueriesListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(warehouseSavedQueriesListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                created_at: zod.iso.datetime({}),
                sync_frequency: zod.string().nullable(),
                columns: zod.array(zod.record(zod.string(), zod.unknown())),
                status: zod
                    .union([
                        zod
                            .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                            .describe(
                                '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                            ),
                        zod.literal(null),
                    ])
                    .nullable()
                    .describe(
                        'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                last_run_at: zod.iso.datetime({}).nullable(),
                managed_viewset_kind: zod.string().nullable(),
                folder_id: zod.uuid().nullable(),
                folder_name: zod.string().nullable(),
                latest_error: zod.string().nullable(),
                is_materialized: zod.boolean().nullable(),
                origin: zod
                    .union([
                        zod
                            .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                            .describe(
                                '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                            ),
                        zod.literal(null),
                    ])
                    .nullable()
                    .describe(
                        'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                is_test: zod.boolean().describe('Whether this view is for testing only and will auto-expire.'),
                expires_at: zod.iso
                    .datetime({})
                    .nullable()
                    .describe('When this test view should be automatically deleted.'),
            })
            .describe('Lightweight serializer for list views - excludes large query field to reduce memory usage.')
    ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesCreateBodyNameMax = 128

export const WarehouseSavedQueriesCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesRetrieveResponseNameMax = 128

export const warehouseSavedQueriesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesRetrieveResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesRetrieveResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesRetrieveResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRetrieveResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(warehouseSavedQueriesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseSavedQueriesRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseSavedQueriesRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseSavedQueriesRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesUpdateBodyNameMax = 128

export const WarehouseSavedQueriesUpdateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesUpdateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesUpdateResponseNameMax = 128

export const warehouseSavedQueriesUpdateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesUpdateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesUpdateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesUpdateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesUpdateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(warehouseSavedQueriesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseSavedQueriesUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseSavedQueriesUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseSavedQueriesUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesPartialUpdateBodyNameMax = 128

export const WarehouseSavedQueriesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesPartialUpdateBodyNameMax)
            .optional()
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesPartialUpdateResponseNameMax = 128

export const warehouseSavedQueriesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesPartialUpdateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesPartialUpdateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod.string().max(warehouseSavedQueriesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseSavedQueriesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseSavedQueriesPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesActivityRetrieveResponseNameMax = 128

export const warehouseSavedQueriesActivityRetrieveResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesActivityRetrieveResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesActivityRetrieveResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesActivityRetrieveResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesActivityRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesActivityRetrieveResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesActivityRetrieveResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesActivityRetrieveResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesActivityRetrieveResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesActivityRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the ancestors of this saved query.

By default, we return the immediate parents. The `level` parameter can be used to
look further back into the ancestor tree. If `level` overshoots (i.e. points to only
ancestors beyond the root), we return an empty list.
 */
export const warehouseSavedQueriesAncestorsCreateBodyNameMax = 128

export const WarehouseSavedQueriesAncestorsCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesAncestorsCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesAncestorsCreateResponseNameMax = 128

export const warehouseSavedQueriesAncestorsCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesAncestorsCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesAncestorsCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesAncestorsCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesAncestorsCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesAncestorsCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesAncestorsCreateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesAncestorsCreateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod.string().max(warehouseSavedQueriesAncestorsCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseSavedQueriesAncestorsCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Cancel a running saved query workflow.
 */
export const warehouseSavedQueriesCancelCreateBodyNameMax = 128

export const WarehouseSavedQueriesCancelCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesCancelCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesCancelCreateResponseNameMax = 128

export const warehouseSavedQueriesCancelCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesCancelCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesCancelCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesCancelCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesCancelCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesCancelCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(warehouseSavedQueriesCancelCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseSavedQueriesCancelCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseSavedQueriesCancelCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseSavedQueriesCancelCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export const warehouseSavedQueriesDependenciesRetrieveResponseNameMax = 128

export const warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesDependenciesRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesDependenciesRetrieveResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesDependenciesRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the descendants of this saved query.

By default, we return the immediate children. The `level` parameter can be used to
look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
descendants further than a leaf), we return an empty list.
 */
export const warehouseSavedQueriesDescendantsCreateBodyNameMax = 128

export const WarehouseSavedQueriesDescendantsCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesDescendantsCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesDescendantsCreateResponseNameMax = 128

export const warehouseSavedQueriesDescendantsCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesDescendantsCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesDescendantsCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesDescendantsCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesDescendantsCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesDescendantsCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesDescendantsCreateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesDescendantsCreateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesDescendantsCreateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesDescendantsCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const warehouseSavedQueriesMaterializeCreateBodyNameMax = 128

export const WarehouseSavedQueriesMaterializeCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesMaterializeCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesMaterializeCreateResponseNameMax = 128

export const warehouseSavedQueriesMaterializeCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesMaterializeCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesMaterializeCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesMaterializeCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesMaterializeCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesMaterializeCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesMaterializeCreateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesMaterializeCreateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesMaterializeCreateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesMaterializeCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export const warehouseSavedQueriesRevertMaterializationCreateBodyNameMax = 128

export const WarehouseSavedQueriesRevertMaterializationCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRevertMaterializationCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesRevertMaterializationCreateResponseNameMax = 128

export const warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesRevertMaterializationCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRevertMaterializationCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesRevertMaterializationCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Run this saved query.
 */
export const warehouseSavedQueriesRunCreateBodyNameMax = 128

export const WarehouseSavedQueriesRunCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesRunCreateResponseNameMax = 128

export const warehouseSavedQueriesRunCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesRunCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesRunCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesRunCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesRunCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(warehouseSavedQueriesRunCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseSavedQueriesRunCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseSavedQueriesRunCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseSavedQueriesRunCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const warehouseSavedQueriesRunHistoryRetrieveResponseNameMax = 128

export const warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesRunHistoryRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunHistoryRetrieveResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesRunHistoryRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Resume paused materialization schedules for multiple matviews.

Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export const warehouseSavedQueriesResumeSchedulesCreateBodyNameMax = 128

export const WarehouseSavedQueriesResumeSchedulesCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesResumeSchedulesCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesResumeSchedulesCreateResponseNameMax = 128

export const warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesResumeSchedulesCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesResumeSchedulesCreateResponseNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key containing the query type. Example: {\"query\": \"SELECT * FROM events LIMIT 100\", \"kind\": \"HogQLQuery\"}'
            ),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(warehouseSavedQueriesResumeSchedulesCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        sync_frequency: zod.string().nullable(),
        columns: zod.array(zod.record(zod.string(), zod.unknown())),
        status: zod
            .union([
                zod
                    .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
            ),
        last_run_at: zod.iso.datetime({}).nullable(),
        managed_viewset_kind: zod.string().nullable(),
        folder_id: zod
            .uuid()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        folder_name: zod
            .string()
            .nullable()
            .describe('Folder name used to organize this view in the SQL editor sidebar.'),
        latest_error: zod.string().nullable(),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        latest_history_id: zod.number().nullable(),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.uuid().nullish().describe('Optional DAG to place this view into'),
        is_materialized: zod.boolean().nullable(),
        origin: zod
            .union([
                zod
                    .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                    .describe(
                        '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
                zod.literal(null),
            ])
            .nullable()
            .describe(
                'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
            ),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
        expires_at: zod.iso.datetime({}).nullable().describe('When this test view should be automatically deleted.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueryFoldersListResponseNameMax = 128

export const warehouseSavedQueryFoldersListResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueryFoldersListResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueryFoldersListResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueryFoldersListResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueryFoldersListResponseItem = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(warehouseSavedQueryFoldersListResponseNameMax)
        .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(warehouseSavedQueryFoldersListResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(warehouseSavedQueryFoldersListResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(warehouseSavedQueryFoldersListResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(warehouseSavedQueryFoldersListResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    view_count: zod.number(),
})
export const WarehouseSavedQueryFoldersListResponse = /* @__PURE__ */ zod.array(
    WarehouseSavedQueryFoldersListResponseItem
)

export const warehouseSavedQueryFoldersCreateBodyNameMax = 128

export const WarehouseSavedQueryFoldersCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(warehouseSavedQueryFoldersCreateBodyNameMax)
        .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
})

export const warehouseSavedQueryFoldersRetrieveResponseNameMax = 128

export const warehouseSavedQueryFoldersRetrieveResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueryFoldersRetrieveResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueryFoldersRetrieveResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueryFoldersRetrieveResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueryFoldersRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(warehouseSavedQueryFoldersRetrieveResponseNameMax)
        .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(warehouseSavedQueryFoldersRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(warehouseSavedQueryFoldersRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(warehouseSavedQueryFoldersRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(warehouseSavedQueryFoldersRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    view_count: zod.number(),
})

export const warehouseSavedQueryFoldersPartialUpdateBodyNameMax = 128

export const WarehouseSavedQueryFoldersPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(warehouseSavedQueryFoldersPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
})

export const warehouseSavedQueryFoldersPartialUpdateResponseNameMax = 128

export const warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneLastNameMax = 150

export const warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneEmailMax = 254

export const WarehouseSavedQueryFoldersPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(warehouseSavedQueryFoldersPartialUpdateResponseNameMax)
        .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneDistinctIdMax)
            .nullish(),
        first_name: zod
            .string()
            .max(warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneFirstNameMax)
            .optional(),
        last_name: zod.string().max(warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(warehouseSavedQueryFoldersPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    view_count: zod.number(),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesListResponseResultsItemNameMax = 128

export const warehouseTablesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseTablesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseTablesListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseTablesListResponseResultsItemCreatedByOneEmailMax = 254

export const warehouseTablesListResponseResultsItemUrlPatternMax = 500

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneEmailMax = 254

export const warehouseTablesListResponseResultsItemCredentialAccessKeyMax = 500

export const warehouseTablesListResponseResultsItemCredentialAccessSecretMax = 500

export const WarehouseTablesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            deleted: zod.boolean().nullish(),
            name: zod.string().max(warehouseTablesListResponseResultsItemNameMax),
            format: zod
                .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
                .describe(
                    '* `CSV` - CSV\n* `CSVWithNames` - CSVWithNames\n* `Parquet` - Parquet\n* `JSONEachRow` - JSON\n* `Delta` - Delta\n* `DeltaS3Wrapper` - DeltaS3Wrapper'
                ),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseTablesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod.string().max(warehouseTablesListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(warehouseTablesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(warehouseTablesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            url_pattern: zod.string().max(warehouseTablesListResponseResultsItemUrlPatternMax),
            credential: zod.object({
                id: zod.uuid(),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(warehouseTablesListResponseResultsItemCredentialCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                created_at: zod.iso.datetime({}),
                access_key: zod.string().max(warehouseTablesListResponseResultsItemCredentialAccessKeyMax),
                access_secret: zod.string().max(warehouseTablesListResponseResultsItemCredentialAccessSecretMax),
            }),
            columns: zod.array(zod.record(zod.string(), zod.unknown())),
            external_data_source: zod.object({
                id: zod.uuid(),
                created_at: zod.iso.datetime({}),
                created_by: zod.number().nullable(),
                status: zod.string(),
                source_type: zod
                    .enum([
                        'Ashby',
                        'Supabase',
                        'CustomerIO',
                        'Github',
                        'Stripe',
                        'Hubspot',
                        'Postgres',
                        'Zendesk',
                        'Snowflake',
                        'Salesforce',
                        'MySQL',
                        'MongoDB',
                        'MSSQL',
                        'Vitally',
                        'BigQuery',
                        'Chargebee',
                        'Clerk',
                        'GoogleAds',
                        'TemporalIO',
                        'DoIt',
                        'GoogleSheets',
                        'MetaAds',
                        'Klaviyo',
                        'Mailchimp',
                        'Braze',
                        'Mailjet',
                        'Redshift',
                        'Polar',
                        'RevenueCat',
                        'LinkedinAds',
                        'RedditAds',
                        'TikTokAds',
                        'BingAds',
                        'Shopify',
                        'Attio',
                        'SnapchatAds',
                        'Linear',
                        'Intercom',
                        'Amplitude',
                        'Mixpanel',
                        'Jira',
                        'ActiveCampaign',
                        'Marketo',
                        'Adjust',
                        'AppsFlyer',
                        'Freshdesk',
                        'GoogleAnalytics',
                        'Pipedrive',
                        'SendGrid',
                        'Slack',
                        'PagerDuty',
                        'Asana',
                        'Notion',
                        'Airtable',
                        'Greenhouse',
                        'BambooHR',
                        'Lever',
                        'GitLab',
                        'Datadog',
                        'Sentry',
                        'Pendo',
                        'FullStory',
                        'AmazonAds',
                        'PinterestAds',
                        'AppleSearchAds',
                        'QuickBooks',
                        'Xero',
                        'NetSuite',
                        'WooCommerce',
                        'BigCommerce',
                        'PayPal',
                        'Square',
                        'Zoom',
                        'Trello',
                        'Monday',
                        'ClickUp',
                        'Confluence',
                        'Recurly',
                        'SalesLoft',
                        'Outreach',
                        'Gong',
                        'Calendly',
                        'Typeform',
                        'Iterable',
                        'ZohoCRM',
                        'Close',
                        'Oracle',
                        'DynamoDB',
                        'Elasticsearch',
                        'Kafka',
                        'LaunchDarkly',
                        'Braintree',
                        'Recharge',
                        'HelpScout',
                        'Gorgias',
                        'Instagram',
                        'YouTubeAnalytics',
                        'FacebookPages',
                        'TwitterAds',
                        'Workday',
                        'ServiceNow',
                        'Pardot',
                        'Copper',
                        'Front',
                        'ChartMogul',
                        'Zuora',
                        'Paddle',
                        'CircleCI',
                        'CockroachDB',
                        'Firebase',
                        'AzureBlob',
                        'GoogleDrive',
                        'OneDrive',
                        'SharePoint',
                        'Box',
                        'SFTP',
                        'MicrosoftTeams',
                        'Aircall',
                        'Webflow',
                        'Okta',
                        'Auth0',
                        'Productboard',
                        'Smartsheet',
                        'Wrike',
                        'Plaid',
                        'SurveyMonkey',
                        'Eventbrite',
                        'RingCentral',
                        'Twilio',
                        'Freshsales',
                        'Shortcut',
                        'ConvertKit',
                        'Drip',
                        'CampaignMonitor',
                        'MailerLite',
                        'Omnisend',
                        'Brevo',
                        'Postmark',
                        'Granola',
                        'BuildBetter',
                        'Convex',
                    ])
                    .describe(
                        '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex'
                    ),
            }),
            external_schema: zod.record(zod.string(), zod.unknown()).nullable(),
            options: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesCreateBodyNameMax = 128

export const warehouseTablesCreateBodyUrlPatternMax = 500

export const warehouseTablesCreateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesCreateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesCreateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesCreateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesCreateBodyCredentialAccessKeyMax = 500

export const warehouseTablesCreateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesCreateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    name: zod.string().max(warehouseTablesCreateBodyNameMax),
    format: zod
        .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
        .describe(
            '* `CSV` - CSV\n* `CSVWithNames` - CSVWithNames\n* `Parquet` - Parquet\n* `JSONEachRow` - JSON\n* `Delta` - Delta\n* `DeltaS3Wrapper` - DeltaS3Wrapper'
        ),
    url_pattern: zod.string().max(warehouseTablesCreateBodyUrlPatternMax),
    credential: zod.object({
        id: zod.uuid(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(warehouseTablesCreateBodyCredentialCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseTablesCreateBodyCredentialCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseTablesCreateBodyCredentialCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseTablesCreateBodyCredentialCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        access_key: zod.string().max(warehouseTablesCreateBodyCredentialAccessKeyMax),
        access_secret: zod.string().max(warehouseTablesCreateBodyCredentialAccessSecretMax),
    }),
    options: zod.record(zod.string(), zod.unknown()).optional(),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesFileCreateBodyNameMax = 128

export const warehouseTablesFileCreateBodyUrlPatternMax = 500

export const warehouseTablesFileCreateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesFileCreateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesFileCreateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesFileCreateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesFileCreateBodyCredentialAccessKeyMax = 500

export const warehouseTablesFileCreateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesFileCreateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    name: zod.string().max(warehouseTablesFileCreateBodyNameMax),
    format: zod
        .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
        .describe(
            '* `CSV` - CSV\n* `CSVWithNames` - CSVWithNames\n* `Parquet` - Parquet\n* `JSONEachRow` - JSON\n* `Delta` - Delta\n* `DeltaS3Wrapper` - DeltaS3Wrapper'
        ),
    url_pattern: zod.string().max(warehouseTablesFileCreateBodyUrlPatternMax),
    credential: zod.object({
        id: zod.uuid(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(warehouseTablesFileCreateBodyCredentialCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseTablesFileCreateBodyCredentialCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseTablesFileCreateBodyCredentialCreatedByOneLastNameMax).optional(),
            email: zod.email().max(warehouseTablesFileCreateBodyCredentialCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        access_key: zod.string().max(warehouseTablesFileCreateBodyCredentialAccessKeyMax),
        access_secret: zod.string().max(warehouseTablesFileCreateBodyCredentialAccessSecretMax),
    }),
    options: zod.record(zod.string(), zod.unknown()).optional(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseViewLinkListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseViewLinkListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseViewLinkListResponseResultsItemCreatedByOneEmailMax = 254

export const warehouseViewLinkListResponseResultsItemSourceTableNameMax = 400

export const warehouseViewLinkListResponseResultsItemSourceTableKeyMax = 400

export const warehouseViewLinkListResponseResultsItemJoiningTableNameMax = 400

export const warehouseViewLinkListResponseResultsItemJoiningTableKeyMax = 400

export const warehouseViewLinkListResponseResultsItemFieldNameMax = 400

export const WarehouseViewLinkListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            deleted: zod.boolean().nullish(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseViewLinkListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseViewLinkListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod.string().max(warehouseViewLinkListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(warehouseViewLinkListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            source_table_name: zod.string().max(warehouseViewLinkListResponseResultsItemSourceTableNameMax),
            source_table_key: zod.string().max(warehouseViewLinkListResponseResultsItemSourceTableKeyMax),
            joining_table_name: zod.string().max(warehouseViewLinkListResponseResultsItemJoiningTableNameMax),
            joining_table_key: zod.string().max(warehouseViewLinkListResponseResultsItemJoiningTableKeyMax),
            field_name: zod.string().max(warehouseViewLinkListResponseResultsItemFieldNameMax),
            configuration: zod.unknown().nullish(),
        })
    ),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkCreateBodySourceTableNameMax = 400

export const warehouseViewLinkCreateBodySourceTableKeyMax = 400

export const warehouseViewLinkCreateBodyJoiningTableNameMax = 400

export const warehouseViewLinkCreateBodyJoiningTableKeyMax = 400

export const warehouseViewLinkCreateBodyFieldNameMax = 400

export const WarehouseViewLinkCreateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinkCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinkCreateBodySourceTableKeyMax),
    joining_table_name: zod.string().max(warehouseViewLinkCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinkCreateBodyJoiningTableKeyMax),
    field_name: zod.string().max(warehouseViewLinkCreateBodyFieldNameMax),
    configuration: zod.unknown().nullish(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkValidateCreateBodyJoiningTableNameMax = 255

export const warehouseViewLinkValidateCreateBodyJoiningTableKeyMax = 255

export const warehouseViewLinkValidateCreateBodySourceTableNameMax = 255

export const warehouseViewLinkValidateCreateBodySourceTableKeyMax = 255

export const WarehouseViewLinkValidateCreateBody = /* @__PURE__ */ zod.object({
    joining_table_name: zod.string().max(warehouseViewLinkValidateCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinkValidateCreateBodyJoiningTableKeyMax),
    source_table_name: zod.string().max(warehouseViewLinkValidateCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinkValidateCreateBodySourceTableKeyMax),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseViewLinksListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseViewLinksListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseViewLinksListResponseResultsItemCreatedByOneEmailMax = 254

export const warehouseViewLinksListResponseResultsItemSourceTableNameMax = 400

export const warehouseViewLinksListResponseResultsItemSourceTableKeyMax = 400

export const warehouseViewLinksListResponseResultsItemJoiningTableNameMax = 400

export const warehouseViewLinksListResponseResultsItemJoiningTableKeyMax = 400

export const warehouseViewLinksListResponseResultsItemFieldNameMax = 400

export const WarehouseViewLinksListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            deleted: zod.boolean().nullish(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseViewLinksListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseViewLinksListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(warehouseViewLinksListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(warehouseViewLinksListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            source_table_name: zod.string().max(warehouseViewLinksListResponseResultsItemSourceTableNameMax),
            source_table_key: zod.string().max(warehouseViewLinksListResponseResultsItemSourceTableKeyMax),
            joining_table_name: zod.string().max(warehouseViewLinksListResponseResultsItemJoiningTableNameMax),
            joining_table_key: zod.string().max(warehouseViewLinksListResponseResultsItemJoiningTableKeyMax),
            field_name: zod.string().max(warehouseViewLinksListResponseResultsItemFieldNameMax),
            configuration: zod.unknown().nullish(),
        })
    ),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksCreateBodySourceTableNameMax = 400

export const warehouseViewLinksCreateBodySourceTableKeyMax = 400

export const warehouseViewLinksCreateBodyJoiningTableNameMax = 400

export const warehouseViewLinksCreateBodyJoiningTableKeyMax = 400

export const warehouseViewLinksCreateBodyFieldNameMax = 400

export const WarehouseViewLinksCreateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinksCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinksCreateBodySourceTableKeyMax),
    joining_table_name: zod.string().max(warehouseViewLinksCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinksCreateBodyJoiningTableKeyMax),
    field_name: zod.string().max(warehouseViewLinksCreateBodyFieldNameMax),
    configuration: zod.unknown().nullish(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksValidateCreateBodyJoiningTableNameMax = 255

export const warehouseViewLinksValidateCreateBodyJoiningTableKeyMax = 255

export const warehouseViewLinksValidateCreateBodySourceTableNameMax = 255

export const warehouseViewLinksValidateCreateBodySourceTableKeyMax = 255

export const WarehouseViewLinksValidateCreateBody = /* @__PURE__ */ zod.object({
    joining_table_name: zod.string().max(warehouseViewLinksValidateCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinksValidateCreateBodyJoiningTableKeyMax),
    source_table_name: zod.string().max(warehouseViewLinksValidateCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinksValidateCreateBodySourceTableKeyMax),
})
