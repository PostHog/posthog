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

/**
 * Start provisioning a managed warehouse for this team.
 */
export const DataWarehouseProvisionCreateBody = /* @__PURE__ */ zod.object({
    database_name: zod.string().describe('Name for the new database'),
})

export const ExternalDataSchemasCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

export const ExternalDataSchemasUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

export const ExternalDataSchemasCancelCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

export const ExternalDataSchemasIncrementalFieldsCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

export const ExternalDataSchemasReloadCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

export const ExternalDataSchemasResyncCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Data type of the incremental field.\n\n\* `integer` - integer\n\* `numeric` - numeric\n\* `datetime` - datetime\n\* `date` - date\n\* `timestamp` - timestamp\n\* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'How often to sync.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
            zod.null(),
        ])
        .optional()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
        ),
    enabled_columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.'
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateBodyAccessMethodDefault = `warehouse`
export const externalDataSourcesCreateBodyCreatedViaDefault = `api`

export const ExternalDataSourcesCreateBody = /* @__PURE__ */ zod.object({
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
            'GoogleSearchConsole',
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
            'ClickHouse',
            'Plain',
            'Resend',
            'PgAnalyze',
            'WorkOS',
            'AmazonS3',
            'GoogleCloudStorage',
            'Databricks',
            'Dynamics365',
            'SalesforceMarketingCloud',
            'Db2',
            'Heap',
            'AdobeAnalytics',
            'Matomo',
            'Optimizely',
            'Adyen',
            'GoCardless',
            'Mollie',
            'CheckoutCom',
            'Branch',
            'Criteo',
            'Outbrain',
            'Taboola',
            'AdRoll',
            'DisplayVideo360',
            'GoogleAdManager',
            'CampaignManager360',
            'SearchAds360',
            'AdobeCommerce',
            'AmazonSellingPartner',
            'Ebay',
            'Commercetools',
            'LightspeedRetail',
            'ShipStation',
            'ConstantContact',
            'Mailgun',
            'Eloqua',
            'Sailthru',
            'Ortto',
            'Attentive',
            'Kustomer',
            'Dixa',
            'Gladly',
            'Qualtrics',
            'Delighted',
            'AzureDevOps',
            'Rollbar',
            'Opsgenie',
            'IncidentIo',
            'Pingdom',
            'Cloudflare',
            'CosmosDB',
            'PlanetScale',
            'SapHana',
            'Rippling',
            'HiBob',
            'Personio',
            'Deel',
            'AdpWorkforceNow',
            'Paylocity',
            'Gusto',
            'CultureAmp',
            'Lattice',
            'SageIntacct',
            'FreshBooks',
            'Expensify',
            'Ramp',
            'Brex',
            'Coupa',
            'SapConcur',
            'Apollo',
            'Crunchbase',
            'ZoomInfo',
            'Clari',
            'Chorus',
            'Coda',
            'Guru',
            'Dropbox',
            'Docusign',
            'PandaDoc',
            'SapErp',
            'SapSuccessFactors',
            'OracleEbs',
            'OracleFusion',
            'AmazonSNS',
            'AmazonEventBridge',
            'AmazonSQS',
            'AmazonKinesis',
            'AmazonCloudWatch',
            'OpenAIAds',
            'Custom',
        ])
        .describe(
            '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
        )
        .describe(
            "The source type (e.g. 'Postgres', 'Stripe').\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe("Connection credentials and a 'schemas' array. Keys depend on source_type."),
    prefix: zod.string().max(externalDataSourcesCreateBodyPrefixMax).nullish().describe('Table name prefix in HogQL.'),
    description: zod
        .string()
        .max(externalDataSourcesCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
    access_method: zod
        .enum(['warehouse', 'direct'])
        .describe('\* `warehouse` - warehouse\n\* `direct` - direct')
        .default(externalDataSourcesCreateBodyAccessMethodDefault)
        .describe(
            "Connection mode: 'warehouse' (import) or 'direct' (live query).\n\n\* `warehouse` - warehouse\n\* `direct` - direct"
        ),
    created_via: zod
        .enum(['web', 'api', 'mcp'])
        .describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp')
        .default(externalDataSourcesCreateBodyCreatedViaDefault)
        .describe('Where the request came from\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateBodyPrefixMax = 100

export const externalDataSourcesUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesBulkUpdateSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    schemas: zod
        .array(
            zod.object({
                id: zod.uuid().describe('Schema identifier to update.'),
                should_sync: zod.boolean().optional().describe('Whether the schema should be queryable\/synced.'),
                sync_type: zod
                    .union([
                        zod
                            .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                            .describe(
                                '\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'Requested sync mode for the schema.\n\n\* `full_refresh` - full_refresh\n\* `incremental` - incremental\n\* `append` - append\n\* `webhook` - webhook\n\* `cdc` - cdc'
                    ),
                incremental_field: zod
                    .string()
                    .nullish()
                    .describe('Incremental cursor field for incremental or append syncs.'),
                incremental_field_type: zod.string().nullish().describe('Type of the incremental cursor field.'),
                sync_frequency: zod.string().nullish().describe('Human-readable sync frequency value.'),
                sync_time_of_day: zod.iso.time({}).nullish().describe('UTC anchor time for scheduled syncs.'),
                cdc_table_mode: zod
                    .union([
                        zod
                            .enum(['consolidated', 'cdc_only', 'both'])
                            .describe('\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'How CDC-backed tables should be exposed.\n\n\* `consolidated` - consolidated\n\* `cdc_only` - cdc_only\n\* `both` - both'
                    ),
                enabled_columns: zod
                    .array(zod.string())
                    .nullish()
                    .describe('Columns to sync. Null means sync all columns.'),
            })
        )
        .optional()
        .describe('Schema updates to apply in a single batch.'),
})

/**
 * Validate CDC prerequisites for an existing source using its stored credentials.
 *
 * The detail=False ``check_cdc_prerequisites`` action is for the creation wizard,
 * where the client still holds the raw connection config (incl. password) in the
 * form. On the Configuration page the source already exists and secret fields are
 * stripped from API responses — so the client can't supply them. This reads the
 * stored (encrypted) credentials from the DB via the adapter instead.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * ``cdc_slot_name`` (optional), ``cdc_publication_name`` (optional).
 */
export const externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyPrefixMax = 100

export const externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCheckCdcPrerequisitesForSourceCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesCheckCdcPrerequisitesForSourceCreateBodyDescriptionMax)
            .nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Disable CDC on an existing source.
 *
 * Cancels any running CDC extraction workflow, deletes the extraction schedule,
 * delegates engine-side teardown to the source's adapter (drops slot/publication
 * for Postgres; equivalent for other engines), clears ``cdc_*`` keys from
 * ``job_inputs``, soft-deletes companion CDC tables, and sets all CDC schemas to
 * ``sync_type=None``, ``should_sync=False`` so the user must pick a new sync
 * strategy before they resume.
 */
export const externalDataSourcesDisableCdcCreateBodyPrefixMax = 100

export const externalDataSourcesDisableCdcCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDisableCdcCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDisableCdcCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDisableCdcCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Enable CDC on an existing source.
 *
 * Provisions engine-side CDC resources via the source's adapter, writes the CDC
 * config into ``source.job_inputs``, and ensures the CDC extraction schedule
 * exists. Re-runs prereq checks server-side so we never trust a stale
 * client-side check.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * plus engine-specific identifier hints (e.g. ``cdc_slot_name``,
 * ``cdc_publication_name`` for Postgres). Universal tuning fields:
 * ``cdc_auto_drop_slot`` (optional bool), ``cdc_lag_warning_threshold_mb``
 * (optional int), ``cdc_lag_critical_threshold_mb`` (optional int).
 */
export const externalDataSourcesEnableCdcCreateBodyPrefixMax = 100

export const externalDataSourcesEnableCdcCreateBodyDescriptionMax = 400

export const ExternalDataSourcesEnableCdcCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesEnableCdcCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesEnableCdcCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const externalDataSourcesRefreshSchemasCreateBodyPrefixMax = 100

export const externalDataSourcesRefreshSchemasCreateBodyDescriptionMax = 400

export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesReloadCreateBodyPrefixMax = 100

export const externalDataSourcesReloadCreateBodyDescriptionMax = 400

export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesReloadCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesReloadCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax)
            .nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update CDC tuning fields without enabling/disabling.
 *
 * Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
 * ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
 * across engines. Engine-specific identifiers (slot name, management mode, …)
 * are immutable post-enable — switching them requires disable + enable.
 */
export const externalDataSourcesUpdateCdcSettingsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateCdcSettingsCreateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateCdcSettingsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateCdcSettingsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateCdcSettingsCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDatabaseSchemaCreateBody = /* @__PURE__ */ zod
    .object({
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
                'GoogleSearchConsole',
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
                'ClickHouse',
                'Plain',
                'Resend',
                'PgAnalyze',
                'WorkOS',
                'AmazonS3',
                'GoogleCloudStorage',
                'Databricks',
                'Dynamics365',
                'SalesforceMarketingCloud',
                'Db2',
                'Heap',
                'AdobeAnalytics',
                'Matomo',
                'Optimizely',
                'Adyen',
                'GoCardless',
                'Mollie',
                'CheckoutCom',
                'Branch',
                'Criteo',
                'Outbrain',
                'Taboola',
                'AdRoll',
                'DisplayVideo360',
                'GoogleAdManager',
                'CampaignManager360',
                'SearchAds360',
                'AdobeCommerce',
                'AmazonSellingPartner',
                'Ebay',
                'Commercetools',
                'LightspeedRetail',
                'ShipStation',
                'ConstantContact',
                'Mailgun',
                'Eloqua',
                'Sailthru',
                'Ortto',
                'Attentive',
                'Kustomer',
                'Dixa',
                'Gladly',
                'Qualtrics',
                'Delighted',
                'AzureDevOps',
                'Rollbar',
                'Opsgenie',
                'IncidentIo',
                'Pingdom',
                'Cloudflare',
                'CosmosDB',
                'PlanetScale',
                'SapHana',
                'Rippling',
                'HiBob',
                'Personio',
                'Deel',
                'AdpWorkforceNow',
                'Paylocity',
                'Gusto',
                'CultureAmp',
                'Lattice',
                'SageIntacct',
                'FreshBooks',
                'Expensify',
                'Ramp',
                'Brex',
                'Coupa',
                'SapConcur',
                'Apollo',
                'Crunchbase',
                'ZoomInfo',
                'Clari',
                'Chorus',
                'Coda',
                'Guru',
                'Dropbox',
                'Docusign',
                'PandaDoc',
                'SapErp',
                'SapSuccessFactors',
                'OracleEbs',
                'OracleFusion',
                'AmazonSNS',
                'AmazonEventBridge',
                'AmazonSQS',
                'AmazonKinesis',
                'AmazonCloudWatch',
                'OpenAIAds',
                'Custom',
            ])
            .describe(
                '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
            )
            .describe(
                'The source type to validate against.\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
            ),
    })
    .describe(
        'Validate credentials and preview available tables from a remote database.\n\nThe request body contains source_type plus flat source-specific credential fields\n(e.g. host, port, database, user, password, schema for Postgres). The credential\nfields vary per source_type and are validated dynamically by the source registry.'
    )

/**
 * One-shot data warehouse source setup.
 *
 * Validate credentials, discover available tables, enable them all with sensible sync defaults
 * (incremental where supported, else append, else full refresh), and create the source in a single
 * call — the caller never has to assemble a `schemas` array. For sources that support webhooks
 * (e.g. Stripe), a webhook is auto-registered after creation: on success webhook-capable tables
 * switch to real-time webhook sync (unlocking webhook-only tables); on failure the polling
 * defaults stay in place. For fine-grained table/sync control, use the lower-level
 * `database_schema` + `create` flow instead.
 */
export const externalDataSourcesSetupCreateBodyPrefixMax = 100

export const externalDataSourcesSetupCreateBodyDescriptionMax = 400

export const ExternalDataSourcesSetupCreateBody = /* @__PURE__ */ zod.object({
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
            'GoogleSearchConsole',
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
            'ClickHouse',
            'Plain',
            'Resend',
            'PgAnalyze',
            'WorkOS',
            'AmazonS3',
            'GoogleCloudStorage',
            'Databricks',
            'Dynamics365',
            'SalesforceMarketingCloud',
            'Db2',
            'Heap',
            'AdobeAnalytics',
            'Matomo',
            'Optimizely',
            'Adyen',
            'GoCardless',
            'Mollie',
            'CheckoutCom',
            'Branch',
            'Criteo',
            'Outbrain',
            'Taboola',
            'AdRoll',
            'DisplayVideo360',
            'GoogleAdManager',
            'CampaignManager360',
            'SearchAds360',
            'AdobeCommerce',
            'AmazonSellingPartner',
            'Ebay',
            'Commercetools',
            'LightspeedRetail',
            'ShipStation',
            'ConstantContact',
            'Mailgun',
            'Eloqua',
            'Sailthru',
            'Ortto',
            'Attentive',
            'Kustomer',
            'Dixa',
            'Gladly',
            'Qualtrics',
            'Delighted',
            'AzureDevOps',
            'Rollbar',
            'Opsgenie',
            'IncidentIo',
            'Pingdom',
            'Cloudflare',
            'CosmosDB',
            'PlanetScale',
            'SapHana',
            'Rippling',
            'HiBob',
            'Personio',
            'Deel',
            'AdpWorkforceNow',
            'Paylocity',
            'Gusto',
            'CultureAmp',
            'Lattice',
            'SageIntacct',
            'FreshBooks',
            'Expensify',
            'Ramp',
            'Brex',
            'Coupa',
            'SapConcur',
            'Apollo',
            'Crunchbase',
            'ZoomInfo',
            'Clari',
            'Chorus',
            'Coda',
            'Guru',
            'Dropbox',
            'Docusign',
            'PandaDoc',
            'SapErp',
            'SapSuccessFactors',
            'OracleEbs',
            'OracleFusion',
            'AmazonSNS',
            'AmazonEventBridge',
            'AmazonSQS',
            'AmazonKinesis',
            'AmazonCloudWatch',
            'OpenAIAds',
            'Custom',
        ])
        .describe(
            '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
        )
        .describe(
            "The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults."
        ),
    prefix: zod
        .string()
        .max(externalDataSourcesSetupCreateBodyPrefixMax)
        .nullish()
        .describe("Table name prefix in HogQL, e.g. 'stripe' produces stripe_charges. Defaults to the source type."),
    description: zod
        .string()
        .max(externalDataSourcesSetupCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesSourcePrefixCreateBodyPrefixMax = 100

export const externalDataSourcesSourcePrefixCreateBodyDescriptionMax = 400

export const ExternalDataSourcesSourcePrefixCreateBody = /* @__PURE__ */ zod
    .object({
        created_via: zod
            .union([
                zod.enum(['web', 'api', 'mcp']).describe('\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent\/MCP tool calls. Ignored on update.\n\n\* `web` - web\n\* `api` - api\n\* `mcp` - mcp'
            ),
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesSourcePrefixCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesSourcePrefixCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Validate and store credentials for a data warehouse source without creating the source.
 *
 * Backs the source connect page: the user enters credentials directly in PostHog, they are
 * checked against a live connection, then stashed encrypted in a temporary store. The returned
 * credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
 * secrets never travel through an agent conversation. The stash is single-use: it is deleted
 * as soon as `setup` consumes it, and expires after 24 hours if never consumed.
 */
export const ExternalDataSourcesStoreCredentialsCreateBody = /* @__PURE__ */ zod.object({
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
            'GoogleSearchConsole',
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
            'ClickHouse',
            'Plain',
            'Resend',
            'PgAnalyze',
            'WorkOS',
            'AmazonS3',
            'GoogleCloudStorage',
            'Databricks',
            'Dynamics365',
            'SalesforceMarketingCloud',
            'Db2',
            'Heap',
            'AdobeAnalytics',
            'Matomo',
            'Optimizely',
            'Adyen',
            'GoCardless',
            'Mollie',
            'CheckoutCom',
            'Branch',
            'Criteo',
            'Outbrain',
            'Taboola',
            'AdRoll',
            'DisplayVideo360',
            'GoogleAdManager',
            'CampaignManager360',
            'SearchAds360',
            'AdobeCommerce',
            'AmazonSellingPartner',
            'Ebay',
            'Commercetools',
            'LightspeedRetail',
            'ShipStation',
            'ConstantContact',
            'Mailgun',
            'Eloqua',
            'Sailthru',
            'Ortto',
            'Attentive',
            'Kustomer',
            'Dixa',
            'Gladly',
            'Qualtrics',
            'Delighted',
            'AzureDevOps',
            'Rollbar',
            'Opsgenie',
            'IncidentIo',
            'Pingdom',
            'Cloudflare',
            'CosmosDB',
            'PlanetScale',
            'SapHana',
            'Rippling',
            'HiBob',
            'Personio',
            'Deel',
            'AdpWorkforceNow',
            'Paylocity',
            'Gusto',
            'CultureAmp',
            'Lattice',
            'SageIntacct',
            'FreshBooks',
            'Expensify',
            'Ramp',
            'Brex',
            'Coupa',
            'SapConcur',
            'Apollo',
            'Crunchbase',
            'ZoomInfo',
            'Clari',
            'Chorus',
            'Coda',
            'Guru',
            'Dropbox',
            'Docusign',
            'PandaDoc',
            'SapErp',
            'SapSuccessFactors',
            'OracleEbs',
            'OracleFusion',
            'AmazonSNS',
            'AmazonEventBridge',
            'AmazonSQS',
            'AmazonKinesis',
            'AmazonCloudWatch',
            'OpenAIAds',
            'Custom',
        ])
        .describe(
            '\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom'
        )
        .describe(
            "The source type these credentials are for (e.g. 'Stripe', 'Postgres').\n\n\* `Ashby` - Ashby\n\* `Supabase` - Supabase\n\* `CustomerIO` - CustomerIO\n\* `Github` - Github\n\* `Stripe` - Stripe\n\* `Hubspot` - Hubspot\n\* `Postgres` - Postgres\n\* `Zendesk` - Zendesk\n\* `Snowflake` - Snowflake\n\* `Salesforce` - Salesforce\n\* `MySQL` - MySQL\n\* `MongoDB` - MongoDB\n\* `MSSQL` - MSSQL\n\* `Vitally` - Vitally\n\* `BigQuery` - BigQuery\n\* `Chargebee` - Chargebee\n\* `Clerk` - Clerk\n\* `GoogleAds` - GoogleAds\n\* `GoogleSearchConsole` - GoogleSearchConsole\n\* `TemporalIO` - TemporalIO\n\* `DoIt` - DoIt\n\* `GoogleSheets` - GoogleSheets\n\* `MetaAds` - MetaAds\n\* `Klaviyo` - Klaviyo\n\* `Mailchimp` - Mailchimp\n\* `Braze` - Braze\n\* `Mailjet` - Mailjet\n\* `Redshift` - Redshift\n\* `Polar` - Polar\n\* `RevenueCat` - RevenueCat\n\* `LinkedinAds` - LinkedinAds\n\* `RedditAds` - RedditAds\n\* `TikTokAds` - TikTokAds\n\* `BingAds` - BingAds\n\* `Shopify` - Shopify\n\* `Attio` - Attio\n\* `SnapchatAds` - SnapchatAds\n\* `Linear` - Linear\n\* `Intercom` - Intercom\n\* `Amplitude` - Amplitude\n\* `Mixpanel` - Mixpanel\n\* `Jira` - Jira\n\* `ActiveCampaign` - ActiveCampaign\n\* `Marketo` - Marketo\n\* `Adjust` - Adjust\n\* `AppsFlyer` - AppsFlyer\n\* `Freshdesk` - Freshdesk\n\* `GoogleAnalytics` - GoogleAnalytics\n\* `Pipedrive` - Pipedrive\n\* `SendGrid` - SendGrid\n\* `Slack` - Slack\n\* `PagerDuty` - PagerDuty\n\* `Asana` - Asana\n\* `Notion` - Notion\n\* `Airtable` - Airtable\n\* `Greenhouse` - Greenhouse\n\* `BambooHR` - BambooHR\n\* `Lever` - Lever\n\* `GitLab` - GitLab\n\* `Datadog` - Datadog\n\* `Sentry` - Sentry\n\* `Pendo` - Pendo\n\* `FullStory` - FullStory\n\* `AmazonAds` - AmazonAds\n\* `PinterestAds` - PinterestAds\n\* `AppleSearchAds` - AppleSearchAds\n\* `QuickBooks` - QuickBooks\n\* `Xero` - Xero\n\* `NetSuite` - NetSuite\n\* `WooCommerce` - WooCommerce\n\* `BigCommerce` - BigCommerce\n\* `PayPal` - PayPal\n\* `Square` - Square\n\* `Zoom` - Zoom\n\* `Trello` - Trello\n\* `Monday` - Monday\n\* `ClickUp` - ClickUp\n\* `Confluence` - Confluence\n\* `Recurly` - Recurly\n\* `SalesLoft` - SalesLoft\n\* `Outreach` - Outreach\n\* `Gong` - Gong\n\* `Calendly` - Calendly\n\* `Typeform` - Typeform\n\* `Iterable` - Iterable\n\* `ZohoCRM` - ZohoCRM\n\* `Close` - Close\n\* `Oracle` - Oracle\n\* `DynamoDB` - DynamoDB\n\* `Elasticsearch` - Elasticsearch\n\* `Kafka` - Kafka\n\* `LaunchDarkly` - LaunchDarkly\n\* `Braintree` - Braintree\n\* `Recharge` - Recharge\n\* `HelpScout` - HelpScout\n\* `Gorgias` - Gorgias\n\* `Instagram` - Instagram\n\* `YouTubeAnalytics` - YouTubeAnalytics\n\* `FacebookPages` - FacebookPages\n\* `TwitterAds` - TwitterAds\n\* `Workday` - Workday\n\* `ServiceNow` - ServiceNow\n\* `Pardot` - Pardot\n\* `Copper` - Copper\n\* `Front` - Front\n\* `ChartMogul` - ChartMogul\n\* `Zuora` - Zuora\n\* `Paddle` - Paddle\n\* `CircleCI` - CircleCI\n\* `CockroachDB` - CockroachDB\n\* `Firebase` - Firebase\n\* `AzureBlob` - AzureBlob\n\* `GoogleDrive` - GoogleDrive\n\* `OneDrive` - OneDrive\n\* `SharePoint` - SharePoint\n\* `Box` - Box\n\* `SFTP` - SFTP\n\* `MicrosoftTeams` - MicrosoftTeams\n\* `Aircall` - Aircall\n\* `Webflow` - Webflow\n\* `Okta` - Okta\n\* `Auth0` - Auth0\n\* `Productboard` - Productboard\n\* `Smartsheet` - Smartsheet\n\* `Wrike` - Wrike\n\* `Plaid` - Plaid\n\* `SurveyMonkey` - SurveyMonkey\n\* `Eventbrite` - Eventbrite\n\* `RingCentral` - RingCentral\n\* `Twilio` - Twilio\n\* `Freshsales` - Freshsales\n\* `Shortcut` - Shortcut\n\* `ConvertKit` - ConvertKit\n\* `Drip` - Drip\n\* `CampaignMonitor` - CampaignMonitor\n\* `MailerLite` - MailerLite\n\* `Omnisend` - Omnisend\n\* `Brevo` - Brevo\n\* `Postmark` - Postmark\n\* `Granola` - Granola\n\* `BuildBetter` - BuildBetter\n\* `Convex` - Convex\n\* `ClickHouse` - ClickHouse\n\* `Plain` - Plain\n\* `Resend` - Resend\n\* `PgAnalyze` - PgAnalyze\n\* `WorkOS` - WorkOS\n\* `AmazonS3` - AmazonS3\n\* `GoogleCloudStorage` - GoogleCloudStorage\n\* `Databricks` - Databricks\n\* `Dynamics365` - Dynamics365\n\* `SalesforceMarketingCloud` - SalesforceMarketingCloud\n\* `Db2` - Db2\n\* `Heap` - Heap\n\* `AdobeAnalytics` - AdobeAnalytics\n\* `Matomo` - Matomo\n\* `Optimizely` - Optimizely\n\* `Adyen` - Adyen\n\* `GoCardless` - GoCardless\n\* `Mollie` - Mollie\n\* `CheckoutCom` - CheckoutCom\n\* `Branch` - Branch\n\* `Criteo` - Criteo\n\* `Outbrain` - Outbrain\n\* `Taboola` - Taboola\n\* `AdRoll` - AdRoll\n\* `DisplayVideo360` - DisplayVideo360\n\* `GoogleAdManager` - GoogleAdManager\n\* `CampaignManager360` - CampaignManager360\n\* `SearchAds360` - SearchAds360\n\* `AdobeCommerce` - AdobeCommerce\n\* `AmazonSellingPartner` - AmazonSellingPartner\n\* `Ebay` - Ebay\n\* `Commercetools` - Commercetools\n\* `LightspeedRetail` - LightspeedRetail\n\* `ShipStation` - ShipStation\n\* `ConstantContact` - ConstantContact\n\* `Mailgun` - Mailgun\n\* `Eloqua` - Eloqua\n\* `Sailthru` - Sailthru\n\* `Ortto` - Ortto\n\* `Attentive` - Attentive\n\* `Kustomer` - Kustomer\n\* `Dixa` - Dixa\n\* `Gladly` - Gladly\n\* `Qualtrics` - Qualtrics\n\* `Delighted` - Delighted\n\* `AzureDevOps` - AzureDevOps\n\* `Rollbar` - Rollbar\n\* `Opsgenie` - Opsgenie\n\* `IncidentIo` - IncidentIo\n\* `Pingdom` - Pingdom\n\* `Cloudflare` - Cloudflare\n\* `CosmosDB` - CosmosDB\n\* `PlanetScale` - PlanetScale\n\* `SapHana` - SapHana\n\* `Rippling` - Rippling\n\* `HiBob` - HiBob\n\* `Personio` - Personio\n\* `Deel` - Deel\n\* `AdpWorkforceNow` - AdpWorkforceNow\n\* `Paylocity` - Paylocity\n\* `Gusto` - Gusto\n\* `CultureAmp` - CultureAmp\n\* `Lattice` - Lattice\n\* `SageIntacct` - SageIntacct\n\* `FreshBooks` - FreshBooks\n\* `Expensify` - Expensify\n\* `Ramp` - Ramp\n\* `Brex` - Brex\n\* `Coupa` - Coupa\n\* `SapConcur` - SapConcur\n\* `Apollo` - Apollo\n\* `Crunchbase` - Crunchbase\n\* `ZoomInfo` - ZoomInfo\n\* `Clari` - Clari\n\* `Chorus` - Chorus\n\* `Coda` - Coda\n\* `Guru` - Guru\n\* `Dropbox` - Dropbox\n\* `Docusign` - Docusign\n\* `PandaDoc` - PandaDoc\n\* `SapErp` - SapErp\n\* `SapSuccessFactors` - SapSuccessFactors\n\* `OracleEbs` - OracleEbs\n\* `OracleFusion` - OracleFusion\n\* `AmazonSNS` - AmazonSNS\n\* `AmazonEventBridge` - AmazonEventBridge\n\* `AmazonSQS` - AmazonSQS\n\* `AmazonKinesis` - AmazonKinesis\n\* `AmazonCloudWatch` - AmazonCloudWatch\n\* `OpenAIAds` - OpenAIAds\n\* `Custom` - Custom"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored.'
        ),
})

export const insightVariablesCreateBodyNameMax = 400

export const InsightVariablesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(insightVariablesCreateBodyNameMax).describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe(
            '\* `String` - String\n\* `Number` - Number\n\* `Boolean` - Boolean\n\* `List` - List\n\* `Date` - Date'
        )
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n\* `String` - String\n\* `Number` - Number\n\* `Boolean` - Boolean\n\* `List` - List\n\* `Date` - Date'
        ),
    default_value: zod.unknown().optional().describe('Default value used when a query references this variable.'),
    values: zod.unknown().optional().describe('Allowed values for List variables. Null for other variable types.'),
})

export const insightVariablesUpdateBodyNameMax = 400

export const InsightVariablesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(insightVariablesUpdateBodyNameMax).describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe(
            '\* `String` - String\n\* `Number` - Number\n\* `Boolean` - Boolean\n\* `List` - List\n\* `Date` - Date'
        )
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n\* `String` - String\n\* `Number` - Number\n\* `Boolean` - Boolean\n\* `List` - List\n\* `Date` - Date'
        ),
    default_value: zod.unknown().optional().describe('Default value used when a query references this variable.'),
    values: zod.unknown().optional().describe('Allowed values for List variables. Null for other variable types.'),
})

export const insightVariablesPartialUpdateBodyNameMax = 400

export const InsightVariablesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(insightVariablesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe(
            '\* `String` - String\n\* `Number` - Number\n\* `Boolean` - Boolean\n\* `List` - List\n\* `Date` - Date'
        )
        .optional()
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n\* `String` - String\n\* `Number` - Number\n\* `Boolean` - Boolean\n\* `List` - List\n\* `Date` - Date'
        ),
    default_value: zod.unknown().optional().describe('Default value used when a query references this variable.'),
    values: zod.unknown().optional().describe('Allowed values for List variables. Null for other variable types.'),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .unknown()
        .optional()
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
        .optional()
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
        .optional()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesCreateBodyNameMax = 128

export const warehouseSavedQueriesCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
export const warehouseSavedQueriesUpdateBodyNameMax = 128

export const warehouseSavedQueriesUpdateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesUpdateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
export const warehouseSavedQueriesPartialUpdateBodyNameMax = 128

export const warehouseSavedQueriesPartialUpdateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesPartialUpdateBodyQueryKindDefault),
                query: zod.string(),
            })
            .optional()
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Return the ancestors of this saved query.
 *
 * By default, we return the immediate parents. The `level` parameter can be used to
 * look further back into the ancestor tree. If `level` overshoots (i.e. points to only
 * ancestors beyond the root), we return an empty list.
 */
export const warehouseSavedQueriesAncestorsCreateBodyNameMax = 128

export const warehouseSavedQueriesAncestorsCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesAncestorsCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Cancel a running saved query workflow.
 */
export const warehouseSavedQueriesCancelCreateBodyNameMax = 128

export const warehouseSavedQueriesCancelCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesCancelCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Return the descendants of this saved query.
 *
 * By default, we return the immediate children. The `level` parameter can be used to
 * look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
 * descendants further than a leaf), we return an empty list.
 */
export const warehouseSavedQueriesDescendantsCreateBodyNameMax = 128

export const warehouseSavedQueriesDescendantsCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesDescendantsCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const warehouseSavedQueriesMaterializeCreateBodyNameMax = 128

export const warehouseSavedQueriesMaterializeCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesMaterializeCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Undo materialization, revert back to the original view.
 * (i.e. delete the materialized table and the schedule)
 */
export const warehouseSavedQueriesRevertMaterializationCreateBodyNameMax = 128

export const warehouseSavedQueriesRevertMaterializationCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod
                    .enum(['HogQLQuery'])
                    .default(warehouseSavedQueriesRevertMaterializationCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Run this saved query.
 */
export const warehouseSavedQueriesRunCreateBodyNameMax = 128

export const warehouseSavedQueriesRunCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesRunCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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
 * Resume paused materialization schedules for multiple matviews.
 *
 * Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
 * This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export const warehouseSavedQueriesResumeSchedulesCreateBodyNameMax = 128

export const warehouseSavedQueriesResumeSchedulesCreateBodyQueryKindDefault = `HogQLQuery`

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
            .object({
                kind: zod.enum(['HogQLQuery']).default(warehouseSavedQueriesResumeSchedulesCreateBodyQueryKindDefault),
                query: zod.string(),
            })
            .describe(
                'HogQL query definition as a JSON object with a \"query\" key containing the SQL string and a \"kind\" key (always \"HogQLQuery\"). Format the SQL string multi-line with indentation and inline `--` comments for non-obvious logic — the SQL editor renders it verbatim, so avoid minified single-line SQL. Example: {\"kind\": \"HogQLQuery\", \"query\": \"SELECT\\n    event,\\n    count() AS cnt\\nFROM events\\nGROUP BY event\\nLIMIT 100\"}'
            ),
        sync_frequency: zod
            .union([
                zod
                    .enum([
                        'never',
                        '1min',
                        '5min',
                        '15min',
                        '30min',
                        '1hour',
                        '6hour',
                        '12hour',
                        '24hour',
                        '7day',
                        '30day',
                    ])
                    .describe(
                        '\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to materialize this view. One of '1min', '5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day', or 'never' to pause scheduled materialization.\n\n\* `never` - never\n\* `1min` - 1min\n\* `5min` - 5min\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
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

export const warehouseSavedQueryFoldersCreateBodyNameMax = 128

export const WarehouseSavedQueryFoldersCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueryFoldersCreateBodyNameMax)
            .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
    })
    .describe('Mixin for serializers to add user access control fields')

export const warehouseSavedQueryFoldersPartialUpdateBodyNameMax = 128

export const WarehouseSavedQueryFoldersPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueryFoldersPartialUpdateBodyNameMax)
            .optional()
            .describe('Display name for the folder used to organize saved queries in the SQL editor sidebar.'),
    })
    .describe('Mixin for serializers to add user access control fields')

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

export const WarehouseTablesCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod.string().max(warehouseTablesCreateBodyNameMax),
        format: zod
            .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
            .describe(
                '\* `CSV` - CSV\n\* `CSVWithNames` - CSVWithNames\n\* `Parquet` - Parquet\n\* `JSONEachRow` - JSON\n\* `Delta` - Delta\n\* `DeltaS3Wrapper` - DeltaS3Wrapper'
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
                                '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .optional(),
            }),
            created_at: zod.iso.datetime({ offset: true }),
            access_key: zod.string().max(warehouseTablesCreateBodyCredentialAccessKeyMax),
            access_secret: zod.string().max(warehouseTablesCreateBodyCredentialAccessSecretMax),
        }),
        options: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesUpdateBodyNameMax = 128

export const warehouseTablesUpdateBodyUrlPatternMax = 500

export const warehouseTablesUpdateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesUpdateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesUpdateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesUpdateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesUpdateBodyCredentialAccessKeyMax = 500

export const warehouseTablesUpdateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesUpdateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod.string().max(warehouseTablesUpdateBodyNameMax),
        format: zod
            .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
            .describe(
                '\* `CSV` - CSV\n\* `CSVWithNames` - CSVWithNames\n\* `Parquet` - Parquet\n\* `JSONEachRow` - JSON\n\* `Delta` - Delta\n\* `DeltaS3Wrapper` - DeltaS3Wrapper'
            ),
        url_pattern: zod.string().max(warehouseTablesUpdateBodyUrlPatternMax),
        credential: zod.object({
            id: zod.uuid(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(warehouseTablesUpdateBodyCredentialCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(warehouseTablesUpdateBodyCredentialCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(warehouseTablesUpdateBodyCredentialCreatedByOneLastNameMax).optional(),
                email: zod.email().max(warehouseTablesUpdateBodyCredentialCreatedByOneEmailMax),
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
                                '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .optional(),
            }),
            created_at: zod.iso.datetime({ offset: true }),
            access_key: zod.string().max(warehouseTablesUpdateBodyCredentialAccessKeyMax),
            access_secret: zod.string().max(warehouseTablesUpdateBodyCredentialAccessSecretMax),
        }),
        options: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesPartialUpdateBodyNameMax = 128

export const warehouseTablesPartialUpdateBodyUrlPatternMax = 500

export const warehouseTablesPartialUpdateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesPartialUpdateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesPartialUpdateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesPartialUpdateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesPartialUpdateBodyCredentialAccessKeyMax = 500

export const warehouseTablesPartialUpdateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod.string().max(warehouseTablesPartialUpdateBodyNameMax).optional(),
        format: zod
            .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
            .optional()
            .describe(
                '\* `CSV` - CSV\n\* `CSVWithNames` - CSVWithNames\n\* `Parquet` - Parquet\n\* `JSONEachRow` - JSON\n\* `Delta` - Delta\n\* `DeltaS3Wrapper` - DeltaS3Wrapper'
            ),
        url_pattern: zod.string().max(warehouseTablesPartialUpdateBodyUrlPatternMax).optional(),
        credential: zod
            .object({
                id: zod.uuid(),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(warehouseTablesPartialUpdateBodyCredentialCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(warehouseTablesPartialUpdateBodyCredentialCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(warehouseTablesPartialUpdateBodyCredentialCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(warehouseTablesPartialUpdateBodyCredentialCreatedByOneEmailMax),
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
                                    '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.null(),
                        ])
                        .optional(),
                }),
                created_at: zod.iso.datetime({ offset: true }),
                access_key: zod.string().max(warehouseTablesPartialUpdateBodyCredentialAccessKeyMax),
                access_secret: zod.string().max(warehouseTablesPartialUpdateBodyCredentialAccessSecretMax),
            })
            .optional(),
        options: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesRefreshSchemaCreateBodyNameMax = 128

export const warehouseTablesRefreshSchemaCreateBodyUrlPatternMax = 500

export const warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesRefreshSchemaCreateBodyCredentialAccessKeyMax = 500

export const warehouseTablesRefreshSchemaCreateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesRefreshSchemaCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod.string().max(warehouseTablesRefreshSchemaCreateBodyNameMax),
        format: zod
            .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
            .describe(
                '\* `CSV` - CSV\n\* `CSVWithNames` - CSVWithNames\n\* `Parquet` - Parquet\n\* `JSONEachRow` - JSON\n\* `Delta` - Delta\n\* `DeltaS3Wrapper` - DeltaS3Wrapper'
            ),
        url_pattern: zod.string().max(warehouseTablesRefreshSchemaCreateBodyUrlPatternMax),
        credential: zod.object({
            id: zod.uuid(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(warehouseTablesRefreshSchemaCreateBodyCredentialCreatedByOneEmailMax),
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
                                '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .optional(),
            }),
            created_at: zod.iso.datetime({ offset: true }),
            access_key: zod.string().max(warehouseTablesRefreshSchemaCreateBodyCredentialAccessKeyMax),
            access_secret: zod.string().max(warehouseTablesRefreshSchemaCreateBodyCredentialAccessSecretMax),
        }),
        options: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesUpdateSchemaCreateBodyNameMax = 128

export const warehouseTablesUpdateSchemaCreateBodyUrlPatternMax = 500

export const warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesUpdateSchemaCreateBodyCredentialAccessKeyMax = 500

export const warehouseTablesUpdateSchemaCreateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesUpdateSchemaCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod.string().max(warehouseTablesUpdateSchemaCreateBodyNameMax),
        format: zod
            .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
            .describe(
                '\* `CSV` - CSV\n\* `CSVWithNames` - CSVWithNames\n\* `Parquet` - Parquet\n\* `JSONEachRow` - JSON\n\* `Delta` - Delta\n\* `DeltaS3Wrapper` - DeltaS3Wrapper'
            ),
        url_pattern: zod.string().max(warehouseTablesUpdateSchemaCreateBodyUrlPatternMax),
        credential: zod.object({
            id: zod.uuid(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(warehouseTablesUpdateSchemaCreateBodyCredentialCreatedByOneEmailMax),
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
                                '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .optional(),
            }),
            created_at: zod.iso.datetime({ offset: true }),
            access_key: zod.string().max(warehouseTablesUpdateSchemaCreateBodyCredentialAccessKeyMax),
            access_secret: zod.string().max(warehouseTablesUpdateSchemaCreateBodyCredentialAccessSecretMax),
        }),
        options: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

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

export const WarehouseTablesFileCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod.string().max(warehouseTablesFileCreateBodyNameMax),
        format: zod
            .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
            .describe(
                '\* `CSV` - CSV\n\* `CSVWithNames` - CSVWithNames\n\* `Parquet` - Parquet\n\* `JSONEachRow` - JSON\n\* `Delta` - Delta\n\* `DeltaS3Wrapper` - DeltaS3Wrapper'
            ),
        url_pattern: zod.string().max(warehouseTablesFileCreateBodyUrlPatternMax),
        credential: zod.object({
            id: zod.uuid(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(warehouseTablesFileCreateBodyCredentialCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseTablesFileCreateBodyCredentialCreatedByOneFirstNameMax)
                    .optional(),
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
                                '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .optional(),
            }),
            created_at: zod.iso.datetime({ offset: true }),
            access_key: zod.string().max(warehouseTablesFileCreateBodyCredentialAccessKeyMax),
            access_secret: zod.string().max(warehouseTablesFileCreateBodyCredentialAccessSecretMax),
        }),
        options: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

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
    configuration: zod.unknown().optional(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkUpdateBodySourceTableNameMax = 400

export const warehouseViewLinkUpdateBodySourceTableKeyMax = 400

export const warehouseViewLinkUpdateBodyJoiningTableNameMax = 400

export const warehouseViewLinkUpdateBodyJoiningTableKeyMax = 400

export const warehouseViewLinkUpdateBodyFieldNameMax = 400

export const WarehouseViewLinkUpdateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinkUpdateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinkUpdateBodySourceTableKeyMax),
    joining_table_name: zod.string().max(warehouseViewLinkUpdateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinkUpdateBodyJoiningTableKeyMax),
    field_name: zod.string().max(warehouseViewLinkUpdateBodyFieldNameMax),
    configuration: zod.unknown().optional(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkPartialUpdateBodySourceTableNameMax = 400

export const warehouseViewLinkPartialUpdateBodySourceTableKeyMax = 400

export const warehouseViewLinkPartialUpdateBodyJoiningTableNameMax = 400

export const warehouseViewLinkPartialUpdateBodyJoiningTableKeyMax = 400

export const warehouseViewLinkPartialUpdateBodyFieldNameMax = 400

export const WarehouseViewLinkPartialUpdateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinkPartialUpdateBodySourceTableNameMax).optional(),
    source_table_key: zod.string().max(warehouseViewLinkPartialUpdateBodySourceTableKeyMax).optional(),
    joining_table_name: zod.string().max(warehouseViewLinkPartialUpdateBodyJoiningTableNameMax).optional(),
    joining_table_key: zod.string().max(warehouseViewLinkPartialUpdateBodyJoiningTableKeyMax).optional(),
    field_name: zod.string().max(warehouseViewLinkPartialUpdateBodyFieldNameMax).optional(),
    configuration: zod.unknown().optional(),
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
    configuration: zod.unknown().optional(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksUpdateBodySourceTableNameMax = 400

export const warehouseViewLinksUpdateBodySourceTableKeyMax = 400

export const warehouseViewLinksUpdateBodyJoiningTableNameMax = 400

export const warehouseViewLinksUpdateBodyJoiningTableKeyMax = 400

export const warehouseViewLinksUpdateBodyFieldNameMax = 400

export const WarehouseViewLinksUpdateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinksUpdateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinksUpdateBodySourceTableKeyMax),
    joining_table_name: zod.string().max(warehouseViewLinksUpdateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinksUpdateBodyJoiningTableKeyMax),
    field_name: zod.string().max(warehouseViewLinksUpdateBodyFieldNameMax),
    configuration: zod.unknown().optional(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksPartialUpdateBodySourceTableNameMax = 400

export const warehouseViewLinksPartialUpdateBodySourceTableKeyMax = 400

export const warehouseViewLinksPartialUpdateBodyJoiningTableNameMax = 400

export const warehouseViewLinksPartialUpdateBodyJoiningTableKeyMax = 400

export const warehouseViewLinksPartialUpdateBodyFieldNameMax = 400

export const WarehouseViewLinksPartialUpdateBody = /* @__PURE__ */ zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinksPartialUpdateBodySourceTableNameMax).optional(),
    source_table_key: zod.string().max(warehouseViewLinksPartialUpdateBodySourceTableKeyMax).optional(),
    joining_table_name: zod.string().max(warehouseViewLinksPartialUpdateBodyJoiningTableNameMax).optional(),
    joining_table_key: zod.string().max(warehouseViewLinksPartialUpdateBodyJoiningTableKeyMax).optional(),
    field_name: zod.string().max(warehouseViewLinksPartialUpdateBodyFieldNameMax).optional(),
    configuration: zod.unknown().optional(),
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
