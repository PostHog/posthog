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

export const batchExportsListResponseResultsItemLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsListResponseResultsItemLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsListResponseResultsItemLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsListResponseResultsItemLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsListResponseResultsItemLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsListResponseResultsItemLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsListResponseResultsItemLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsListResponseResultsItemLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsListResponseResultsItemOffsetDayMin = 0
export const batchExportsListResponseResultsItemOffsetDayMax = 6

export const batchExportsListResponseResultsItemOffsetHourMin = 0
export const batchExportsListResponseResultsItemOffsetHourMax = 23

export const BatchExportsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                team_id: zod.number().describe('The team this belongs to.'),
                name: zod.string().describe('A human-readable name for this BatchExport.'),
                model: zod
                    .union([
                        zod
                            .enum(['events', 'persons', 'sessions'])
                            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
                    ),
                destination: zod
                    .object({
                        type: zod
                            .enum([
                                'S3',
                                'Snowflake',
                                'Postgres',
                                'Redshift',
                                'BigQuery',
                                'Databricks',
                                'AzureBlob',
                                'Workflows',
                                'HTTP',
                                'NoOp',
                            ])
                            .describe(
                                '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                            )
                            .describe(
                                'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                            ),
                        config: zod
                            .unknown()
                            .optional()
                            .describe(
                                'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                            ),
                        integration: zod.number().nullish().describe('The integration for this destination.'),
                        integration_id: zod.number().nullish(),
                    })
                    .describe('Serializer for an BatchExportDestination model.'),
                interval: zod
                    .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
                    .describe(
                        '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
                    ),
                paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
                created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
                last_updated_at: zod.iso
                    .datetime({})
                    .describe('The timestamp at which this BatchExport was last updated.'),
                last_paused_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe('The timestamp at which this BatchExport was last paused.'),
                start_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe("Time before which any Batch Export runs won't be triggered."),
                end_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe("Time after which any Batch Export runs won't be triggered."),
                latest_runs: zod.array(
                    zod
                        .object({
                            id: zod.uuid(),
                            status: zod
                                .enum([
                                    'Cancelled',
                                    'Completed',
                                    'ContinuedAsNew',
                                    'Failed',
                                    'FailedRetryable',
                                    'FailedBilling',
                                    'Terminated',
                                    'TimedOut',
                                    'Running',
                                    'Starting',
                                ])
                                .describe(
                                    '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                                )
                                .describe(
                                    'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                                ),
                            records_completed: zod
                                .number()
                                .min(batchExportsListResponseResultsItemLatestRunsItemRecordsCompletedMin)
                                .max(batchExportsListResponseResultsItemLatestRunsItemRecordsCompletedMax)
                                .nullish()
                                .describe('The number of records that have been exported.'),
                            records_failed: zod
                                .number()
                                .min(batchExportsListResponseResultsItemLatestRunsItemRecordsFailedMin)
                                .max(batchExportsListResponseResultsItemLatestRunsItemRecordsFailedMax)
                                .nullish()
                                .describe(
                                    'The number of records that failed downstream processing (e.g. hog function execution errors).'
                                ),
                            latest_error: zod
                                .string()
                                .nullish()
                                .describe('The latest error that occurred during this run.'),
                            data_interval_start: zod.iso
                                .datetime({})
                                .nullish()
                                .describe('The start of the data interval.'),
                            data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                            cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                            created_at: zod.iso
                                .datetime({})
                                .describe('The timestamp at which this BatchExportRun was created.'),
                            finished_at: zod.iso
                                .datetime({})
                                .nullish()
                                .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                            last_updated_at: zod.iso
                                .datetime({})
                                .describe('The timestamp at which this BatchExportRun was last updated.'),
                            records_total_count: zod
                                .number()
                                .min(batchExportsListResponseResultsItemLatestRunsItemRecordsTotalCountMin)
                                .max(batchExportsListResponseResultsItemLatestRunsItemRecordsTotalCountMax)
                                .nullish()
                                .describe('The total count of records that should be exported in this BatchExportRun.'),
                            bytes_exported: zod
                                .number()
                                .min(batchExportsListResponseResultsItemLatestRunsItemBytesExportedMin)
                                .max(batchExportsListResponseResultsItemLatestRunsItemBytesExportedMax)
                                .nullish()
                                .describe('The number of bytes that have been exported in this BatchExportRun.'),
                            batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                            backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                        })
                        .describe('Serializer for a BatchExportRun model.')
                ),
                hogql_query: zod.string().optional(),
                schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
                filters: zod.unknown().nullish(),
                timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
                offset_day: zod
                    .number()
                    .min(batchExportsListResponseResultsItemOffsetDayMin)
                    .max(batchExportsListResponseResultsItemOffsetDayMax)
                    .nullish(),
                offset_hour: zod
                    .number()
                    .min(batchExportsListResponseResultsItemOffsetHourMin)
                    .max(batchExportsListResponseResultsItemOffsetHourMax)
                    .nullish(),
            })
            .describe('Serializer for a BatchExport model.')
    ),
})

export const batchExportsCreateBodyOffsetDayMin = 0
export const batchExportsCreateBodyOffsetDayMax = 6

export const batchExportsCreateBodyOffsetHourMin = 0
export const batchExportsCreateBodyOffsetHourMax = 23

export const BatchExportsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsCreateBodyOffsetDayMin)
            .max(batchExportsCreateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsCreateBodyOffsetHourMin)
            .max(batchExportsCreateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRetrieveResponseLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsRetrieveResponseLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsRetrieveResponseLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsRetrieveResponseLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsRetrieveResponseLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsRetrieveResponseLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsRetrieveResponseLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsRetrieveResponseLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsRetrieveResponseOffsetDayMin = 0
export const batchExportsRetrieveResponseOffsetDayMax = 6

export const batchExportsRetrieveResponseOffsetHourMin = 0
export const batchExportsRetrieveResponseOffsetHourMax = 23

export const BatchExportsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number().describe('The team this belongs to.'),
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was last updated.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        latest_runs: zod.array(
            zod
                .object({
                    id: zod.uuid(),
                    status: zod
                        .enum([
                            'Cancelled',
                            'Completed',
                            'ContinuedAsNew',
                            'Failed',
                            'FailedRetryable',
                            'FailedBilling',
                            'Terminated',
                            'TimedOut',
                            'Running',
                            'Starting',
                        ])
                        .describe(
                            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        )
                        .describe(
                            'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        ),
                    records_completed: zod
                        .number()
                        .min(batchExportsRetrieveResponseLatestRunsItemRecordsCompletedMin)
                        .max(batchExportsRetrieveResponseLatestRunsItemRecordsCompletedMax)
                        .nullish()
                        .describe('The number of records that have been exported.'),
                    records_failed: zod
                        .number()
                        .min(batchExportsRetrieveResponseLatestRunsItemRecordsFailedMin)
                        .max(batchExportsRetrieveResponseLatestRunsItemRecordsFailedMax)
                        .nullish()
                        .describe(
                            'The number of records that failed downstream processing (e.g. hog function execution errors).'
                        ),
                    latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                    data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                    data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                    cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                    created_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was created.'),
                    finished_at: zod.iso
                        .datetime({})
                        .nullish()
                        .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                    last_updated_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was last updated.'),
                    records_total_count: zod
                        .number()
                        .min(batchExportsRetrieveResponseLatestRunsItemRecordsTotalCountMin)
                        .max(batchExportsRetrieveResponseLatestRunsItemRecordsTotalCountMax)
                        .nullish()
                        .describe('The total count of records that should be exported in this BatchExportRun.'),
                    bytes_exported: zod
                        .number()
                        .min(batchExportsRetrieveResponseLatestRunsItemBytesExportedMin)
                        .max(batchExportsRetrieveResponseLatestRunsItemBytesExportedMax)
                        .nullish()
                        .describe('The number of bytes that have been exported in this BatchExportRun.'),
                    batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                    backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                })
                .describe('Serializer for a BatchExportRun model.')
        ),
        hogql_query: zod.string().optional(),
        schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsRetrieveResponseOffsetDayMin)
            .max(batchExportsRetrieveResponseOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsRetrieveResponseOffsetHourMin)
            .max(batchExportsRetrieveResponseOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsUpdateBodyOffsetDayMin = 0
export const batchExportsUpdateBodyOffsetDayMax = 6

export const batchExportsUpdateBodyOffsetHourMin = 0
export const batchExportsUpdateBodyOffsetHourMax = 23

export const BatchExportsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsUpdateBodyOffsetDayMin)
            .max(batchExportsUpdateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsUpdateBodyOffsetHourMin)
            .max(batchExportsUpdateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsUpdateResponseLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsUpdateResponseLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsUpdateResponseLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsUpdateResponseLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsUpdateResponseLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsUpdateResponseLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsUpdateResponseLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsUpdateResponseLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsUpdateResponseOffsetDayMin = 0
export const batchExportsUpdateResponseOffsetDayMax = 6

export const batchExportsUpdateResponseOffsetHourMin = 0
export const batchExportsUpdateResponseOffsetHourMax = 23

export const BatchExportsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number().describe('The team this belongs to.'),
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was last updated.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        latest_runs: zod.array(
            zod
                .object({
                    id: zod.uuid(),
                    status: zod
                        .enum([
                            'Cancelled',
                            'Completed',
                            'ContinuedAsNew',
                            'Failed',
                            'FailedRetryable',
                            'FailedBilling',
                            'Terminated',
                            'TimedOut',
                            'Running',
                            'Starting',
                        ])
                        .describe(
                            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        )
                        .describe(
                            'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        ),
                    records_completed: zod
                        .number()
                        .min(batchExportsUpdateResponseLatestRunsItemRecordsCompletedMin)
                        .max(batchExportsUpdateResponseLatestRunsItemRecordsCompletedMax)
                        .nullish()
                        .describe('The number of records that have been exported.'),
                    records_failed: zod
                        .number()
                        .min(batchExportsUpdateResponseLatestRunsItemRecordsFailedMin)
                        .max(batchExportsUpdateResponseLatestRunsItemRecordsFailedMax)
                        .nullish()
                        .describe(
                            'The number of records that failed downstream processing (e.g. hog function execution errors).'
                        ),
                    latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                    data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                    data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                    cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                    created_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was created.'),
                    finished_at: zod.iso
                        .datetime({})
                        .nullish()
                        .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                    last_updated_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was last updated.'),
                    records_total_count: zod
                        .number()
                        .min(batchExportsUpdateResponseLatestRunsItemRecordsTotalCountMin)
                        .max(batchExportsUpdateResponseLatestRunsItemRecordsTotalCountMax)
                        .nullish()
                        .describe('The total count of records that should be exported in this BatchExportRun.'),
                    bytes_exported: zod
                        .number()
                        .min(batchExportsUpdateResponseLatestRunsItemBytesExportedMin)
                        .max(batchExportsUpdateResponseLatestRunsItemBytesExportedMax)
                        .nullish()
                        .describe('The number of bytes that have been exported in this BatchExportRun.'),
                    batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                    backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                })
                .describe('Serializer for a BatchExportRun model.')
        ),
        hogql_query: zod.string().optional(),
        schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsUpdateResponseOffsetDayMin)
            .max(batchExportsUpdateResponseOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsUpdateResponseOffsetHourMin)
            .max(batchExportsUpdateResponseOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsPartialUpdateBodyOffsetDayMin = 0
export const batchExportsPartialUpdateBodyOffsetDayMax = 6

export const batchExportsPartialUpdateBodyOffsetHourMin = 0
export const batchExportsPartialUpdateBodyOffsetHourMax = 23

export const BatchExportsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().optional().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .optional()
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .optional()
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsPartialUpdateBodyOffsetDayMin)
            .max(batchExportsPartialUpdateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsPartialUpdateBodyOffsetHourMin)
            .max(batchExportsPartialUpdateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsPartialUpdateResponseLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsPartialUpdateResponseLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsPartialUpdateResponseLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsPartialUpdateResponseLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsPartialUpdateResponseLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsPartialUpdateResponseLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsPartialUpdateResponseLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsPartialUpdateResponseLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsPartialUpdateResponseOffsetDayMin = 0
export const batchExportsPartialUpdateResponseOffsetDayMax = 6

export const batchExportsPartialUpdateResponseOffsetHourMin = 0
export const batchExportsPartialUpdateResponseOffsetHourMax = 23

export const BatchExportsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number().describe('The team this belongs to.'),
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was last updated.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        latest_runs: zod.array(
            zod
                .object({
                    id: zod.uuid(),
                    status: zod
                        .enum([
                            'Cancelled',
                            'Completed',
                            'ContinuedAsNew',
                            'Failed',
                            'FailedRetryable',
                            'FailedBilling',
                            'Terminated',
                            'TimedOut',
                            'Running',
                            'Starting',
                        ])
                        .describe(
                            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        )
                        .describe(
                            'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        ),
                    records_completed: zod
                        .number()
                        .min(batchExportsPartialUpdateResponseLatestRunsItemRecordsCompletedMin)
                        .max(batchExportsPartialUpdateResponseLatestRunsItemRecordsCompletedMax)
                        .nullish()
                        .describe('The number of records that have been exported.'),
                    records_failed: zod
                        .number()
                        .min(batchExportsPartialUpdateResponseLatestRunsItemRecordsFailedMin)
                        .max(batchExportsPartialUpdateResponseLatestRunsItemRecordsFailedMax)
                        .nullish()
                        .describe(
                            'The number of records that failed downstream processing (e.g. hog function execution errors).'
                        ),
                    latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                    data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                    data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                    cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                    created_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was created.'),
                    finished_at: zod.iso
                        .datetime({})
                        .nullish()
                        .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                    last_updated_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was last updated.'),
                    records_total_count: zod
                        .number()
                        .min(batchExportsPartialUpdateResponseLatestRunsItemRecordsTotalCountMin)
                        .max(batchExportsPartialUpdateResponseLatestRunsItemRecordsTotalCountMax)
                        .nullish()
                        .describe('The total count of records that should be exported in this BatchExportRun.'),
                    bytes_exported: zod
                        .number()
                        .min(batchExportsPartialUpdateResponseLatestRunsItemBytesExportedMin)
                        .max(batchExportsPartialUpdateResponseLatestRunsItemBytesExportedMax)
                        .nullish()
                        .describe('The number of bytes that have been exported in this BatchExportRun.'),
                    batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                    backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                })
                .describe('Serializer for a BatchExportRun model.')
        ),
        hogql_query: zod.string().optional(),
        schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsPartialUpdateResponseOffsetDayMin)
            .max(batchExportsPartialUpdateResponseOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsPartialUpdateResponseOffsetHourMin)
            .max(batchExportsPartialUpdateResponseOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

/**
 * Pause a BatchExport.
 */
export const batchExportsPauseCreateBodyOffsetDayMin = 0
export const batchExportsPauseCreateBodyOffsetDayMax = 6

export const batchExportsPauseCreateBodyOffsetHourMin = 0
export const batchExportsPauseCreateBodyOffsetHourMax = 23

export const BatchExportsPauseCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsPauseCreateBodyOffsetDayMin)
            .max(batchExportsPauseCreateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsPauseCreateBodyOffsetHourMin)
            .max(batchExportsPauseCreateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRunTestStepCreateBodyOffsetDayMin = 0
export const batchExportsRunTestStepCreateBodyOffsetDayMax = 6

export const batchExportsRunTestStepCreateBodyOffsetHourMin = 0
export const batchExportsRunTestStepCreateBodyOffsetHourMax = 23

export const BatchExportsRunTestStepCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsRunTestStepCreateBodyOffsetDayMin)
            .max(batchExportsRunTestStepCreateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsRunTestStepCreateBodyOffsetHourMin)
            .max(batchExportsRunTestStepCreateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

/**
 * Unpause a BatchExport.
 */
export const batchExportsUnpauseCreateBodyOffsetDayMin = 0
export const batchExportsUnpauseCreateBodyOffsetDayMax = 6

export const batchExportsUnpauseCreateBodyOffsetHourMin = 0
export const batchExportsUnpauseCreateBodyOffsetHourMax = 23

export const BatchExportsUnpauseCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsUnpauseCreateBodyOffsetDayMin)
            .max(batchExportsUnpauseCreateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsUnpauseCreateBodyOffsetHourMin)
            .max(batchExportsUnpauseCreateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRunTestStepNewCreateBodyOffsetDayMin = 0
export const batchExportsRunTestStepNewCreateBodyOffsetDayMax = 6

export const batchExportsRunTestStepNewCreateBodyOffsetHourMin = 0
export const batchExportsRunTestStepNewCreateBodyOffsetHourMax = 23

export const BatchExportsRunTestStepNewCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsRunTestStepNewCreateBodyOffsetDayMin)
            .max(batchExportsRunTestStepNewCreateBodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsRunTestStepNewCreateBodyOffsetHourMin)
            .max(batchExportsRunTestStepNewCreateBodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsList2ResponseResultsItemLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsList2ResponseResultsItemLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsList2ResponseResultsItemLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsList2ResponseResultsItemLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsList2ResponseResultsItemLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsList2ResponseResultsItemLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsList2ResponseResultsItemLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsList2ResponseResultsItemLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsList2ResponseResultsItemOffsetDayMin = 0
export const batchExportsList2ResponseResultsItemOffsetDayMax = 6

export const batchExportsList2ResponseResultsItemOffsetHourMin = 0
export const batchExportsList2ResponseResultsItemOffsetHourMax = 23

export const BatchExportsList2Response = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                team_id: zod.number().describe('The team this belongs to.'),
                name: zod.string().describe('A human-readable name for this BatchExport.'),
                model: zod
                    .union([
                        zod
                            .enum(['events', 'persons', 'sessions'])
                            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
                    ),
                destination: zod
                    .object({
                        type: zod
                            .enum([
                                'S3',
                                'Snowflake',
                                'Postgres',
                                'Redshift',
                                'BigQuery',
                                'Databricks',
                                'AzureBlob',
                                'Workflows',
                                'HTTP',
                                'NoOp',
                            ])
                            .describe(
                                '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                            )
                            .describe(
                                'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                            ),
                        config: zod
                            .unknown()
                            .optional()
                            .describe(
                                'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                            ),
                        integration: zod.number().nullish().describe('The integration for this destination.'),
                        integration_id: zod.number().nullish(),
                    })
                    .describe('Serializer for an BatchExportDestination model.'),
                interval: zod
                    .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
                    .describe(
                        '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
                    ),
                paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
                created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
                last_updated_at: zod.iso
                    .datetime({})
                    .describe('The timestamp at which this BatchExport was last updated.'),
                last_paused_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe('The timestamp at which this BatchExport was last paused.'),
                start_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe("Time before which any Batch Export runs won't be triggered."),
                end_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe("Time after which any Batch Export runs won't be triggered."),
                latest_runs: zod.array(
                    zod
                        .object({
                            id: zod.uuid(),
                            status: zod
                                .enum([
                                    'Cancelled',
                                    'Completed',
                                    'ContinuedAsNew',
                                    'Failed',
                                    'FailedRetryable',
                                    'FailedBilling',
                                    'Terminated',
                                    'TimedOut',
                                    'Running',
                                    'Starting',
                                ])
                                .describe(
                                    '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                                )
                                .describe(
                                    'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                                ),
                            records_completed: zod
                                .number()
                                .min(batchExportsList2ResponseResultsItemLatestRunsItemRecordsCompletedMin)
                                .max(batchExportsList2ResponseResultsItemLatestRunsItemRecordsCompletedMax)
                                .nullish()
                                .describe('The number of records that have been exported.'),
                            records_failed: zod
                                .number()
                                .min(batchExportsList2ResponseResultsItemLatestRunsItemRecordsFailedMin)
                                .max(batchExportsList2ResponseResultsItemLatestRunsItemRecordsFailedMax)
                                .nullish()
                                .describe(
                                    'The number of records that failed downstream processing (e.g. hog function execution errors).'
                                ),
                            latest_error: zod
                                .string()
                                .nullish()
                                .describe('The latest error that occurred during this run.'),
                            data_interval_start: zod.iso
                                .datetime({})
                                .nullish()
                                .describe('The start of the data interval.'),
                            data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                            cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                            created_at: zod.iso
                                .datetime({})
                                .describe('The timestamp at which this BatchExportRun was created.'),
                            finished_at: zod.iso
                                .datetime({})
                                .nullish()
                                .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                            last_updated_at: zod.iso
                                .datetime({})
                                .describe('The timestamp at which this BatchExportRun was last updated.'),
                            records_total_count: zod
                                .number()
                                .min(batchExportsList2ResponseResultsItemLatestRunsItemRecordsTotalCountMin)
                                .max(batchExportsList2ResponseResultsItemLatestRunsItemRecordsTotalCountMax)
                                .nullish()
                                .describe('The total count of records that should be exported in this BatchExportRun.'),
                            bytes_exported: zod
                                .number()
                                .min(batchExportsList2ResponseResultsItemLatestRunsItemBytesExportedMin)
                                .max(batchExportsList2ResponseResultsItemLatestRunsItemBytesExportedMax)
                                .nullish()
                                .describe('The number of bytes that have been exported in this BatchExportRun.'),
                            batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                            backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                        })
                        .describe('Serializer for a BatchExportRun model.')
                ),
                hogql_query: zod.string().optional(),
                schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
                filters: zod.unknown().nullish(),
                timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
                offset_day: zod
                    .number()
                    .min(batchExportsList2ResponseResultsItemOffsetDayMin)
                    .max(batchExportsList2ResponseResultsItemOffsetDayMax)
                    .nullish(),
                offset_hour: zod
                    .number()
                    .min(batchExportsList2ResponseResultsItemOffsetHourMin)
                    .max(batchExportsList2ResponseResultsItemOffsetHourMax)
                    .nullish(),
            })
            .describe('Serializer for a BatchExport model.')
    ),
})

export const batchExportsCreate2BodyOffsetDayMin = 0
export const batchExportsCreate2BodyOffsetDayMax = 6

export const batchExportsCreate2BodyOffsetHourMin = 0
export const batchExportsCreate2BodyOffsetHourMax = 23

export const BatchExportsCreate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsCreate2BodyOffsetDayMin)
            .max(batchExportsCreate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsCreate2BodyOffsetHourMin)
            .max(batchExportsCreate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const batchExportsBackfillsListResponseResultsItemTotalRecordsCountMin = -9223372036854776000
export const batchExportsBackfillsListResponseResultsItemTotalRecordsCountMax = 9223372036854776000

export const BatchExportsBackfillsListResponse = /* @__PURE__ */ zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            progress: zod
                .object({
                    total_runs: zod.number().nullish(),
                    finished_runs: zod.number().nullish(),
                    progress: zod.number().nullish(),
                })
                .nullable(),
            start_at: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
            end_at: zod.iso.datetime({}).nullish().describe('The end of the data interval.'),
            status: zod
                .enum([
                    'Cancelled',
                    'Completed',
                    'ContinuedAsNew',
                    'Failed',
                    'FailedRetryable',
                    'Terminated',
                    'TimedOut',
                    'Running',
                    'Starting',
                ])
                .describe(
                    '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                )
                .describe(
                    'The status of this backfill.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                ),
            created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExportBackfill was created.'),
            finished_at: zod.iso
                .datetime({})
                .nullish()
                .describe('The timestamp at which this BatchExportBackfill finished, successfully or not.'),
            last_updated_at: zod.iso
                .datetime({})
                .describe('The timestamp at which this BatchExportBackfill was last updated.'),
            total_records_count: zod
                .number()
                .min(batchExportsBackfillsListResponseResultsItemTotalRecordsCountMin)
                .max(batchExportsBackfillsListResponseResultsItemTotalRecordsCountMax)
                .nullish()
                .describe(
                    'The total number of records to export. Initially estimated, updated with actual count after completion.'
                ),
            adjusted_start_at: zod.iso
                .datetime({})
                .nullish()
                .describe(
                    'The actual start time after adjustment for earliest available data. May differ from start_at if user requested a date before data exists.'
                ),
            team: zod.number().describe('The team this belongs to.'),
            batch_export: zod.uuid().describe('The BatchExport this backfill belongs to.'),
        })
    ),
})

/**
 * Create a new backfill for a BatchExport.
 */
export const batchExportsBackfillsCreateBodyTotalRecordsCountMin = -9223372036854776000
export const batchExportsBackfillsCreateBodyTotalRecordsCountMax = 9223372036854776000

export const BatchExportsBackfillsCreateBody = /* @__PURE__ */ zod.object({
    start_at: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
    end_at: zod.iso.datetime({}).nullish().describe('The end of the data interval.'),
    status: zod
        .enum([
            'Cancelled',
            'Completed',
            'ContinuedAsNew',
            'Failed',
            'FailedRetryable',
            'Terminated',
            'TimedOut',
            'Running',
            'Starting',
        ])
        .describe(
            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
        )
        .describe(
            'The status of this backfill.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
        ),
    finished_at: zod.iso
        .datetime({})
        .nullish()
        .describe('The timestamp at which this BatchExportBackfill finished, successfully or not.'),
    total_records_count: zod
        .number()
        .min(batchExportsBackfillsCreateBodyTotalRecordsCountMin)
        .max(batchExportsBackfillsCreateBodyTotalRecordsCountMax)
        .nullish()
        .describe(
            'The total number of records to export. Initially estimated, updated with actual count after completion.'
        ),
    adjusted_start_at: zod.iso
        .datetime({})
        .nullish()
        .describe(
            'The actual start time after adjustment for earliest available data. May differ from start_at if user requested a date before data exists.'
        ),
    team: zod.number().describe('The team this belongs to.'),
    batch_export: zod.uuid().describe('The BatchExport this backfill belongs to.'),
})

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const batchExportsBackfillsRetrieveResponseTotalRecordsCountMin = -9223372036854776000
export const batchExportsBackfillsRetrieveResponseTotalRecordsCountMax = 9223372036854776000

export const BatchExportsBackfillsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    progress: zod
        .object({
            total_runs: zod.number().nullish(),
            finished_runs: zod.number().nullish(),
            progress: zod.number().nullish(),
        })
        .nullable(),
    start_at: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
    end_at: zod.iso.datetime({}).nullish().describe('The end of the data interval.'),
    status: zod
        .enum([
            'Cancelled',
            'Completed',
            'ContinuedAsNew',
            'Failed',
            'FailedRetryable',
            'Terminated',
            'TimedOut',
            'Running',
            'Starting',
        ])
        .describe(
            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
        )
        .describe(
            'The status of this backfill.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
        ),
    created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExportBackfill was created.'),
    finished_at: zod.iso
        .datetime({})
        .nullish()
        .describe('The timestamp at which this BatchExportBackfill finished, successfully or not.'),
    last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExportBackfill was last updated.'),
    total_records_count: zod
        .number()
        .min(batchExportsBackfillsRetrieveResponseTotalRecordsCountMin)
        .max(batchExportsBackfillsRetrieveResponseTotalRecordsCountMax)
        .nullish()
        .describe(
            'The total number of records to export. Initially estimated, updated with actual count after completion.'
        ),
    adjusted_start_at: zod.iso
        .datetime({})
        .nullish()
        .describe(
            'The actual start time after adjustment for earliest available data. May differ from start_at if user requested a date before data exists.'
        ),
    team: zod.number().describe('The team this belongs to.'),
    batch_export: zod.uuid().describe('The BatchExport this backfill belongs to.'),
})

/**
 * Cancel a batch export backfill.
 */
export const batchExportsBackfillsCancelCreateBodyTotalRecordsCountMin = -9223372036854776000
export const batchExportsBackfillsCancelCreateBodyTotalRecordsCountMax = 9223372036854776000

export const BatchExportsBackfillsCancelCreateBody = /* @__PURE__ */ zod.object({
    start_at: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
    end_at: zod.iso.datetime({}).nullish().describe('The end of the data interval.'),
    status: zod
        .enum([
            'Cancelled',
            'Completed',
            'ContinuedAsNew',
            'Failed',
            'FailedRetryable',
            'Terminated',
            'TimedOut',
            'Running',
            'Starting',
        ])
        .describe(
            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
        )
        .describe(
            'The status of this backfill.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
        ),
    finished_at: zod.iso
        .datetime({})
        .nullish()
        .describe('The timestamp at which this BatchExportBackfill finished, successfully or not.'),
    total_records_count: zod
        .number()
        .min(batchExportsBackfillsCancelCreateBodyTotalRecordsCountMin)
        .max(batchExportsBackfillsCancelCreateBodyTotalRecordsCountMax)
        .nullish()
        .describe(
            'The total number of records to export. Initially estimated, updated with actual count after completion.'
        ),
    adjusted_start_at: zod.iso
        .datetime({})
        .nullish()
        .describe(
            'The actual start time after adjustment for earliest available data. May differ from start_at if user requested a date before data exists.'
        ),
    team: zod.number().describe('The team this belongs to.'),
    batch_export: zod.uuid().describe('The BatchExport this backfill belongs to.'),
})

export const batchExportsRunsListResponseResultsItemRecordsCompletedMin = -2147483648
export const batchExportsRunsListResponseResultsItemRecordsCompletedMax = 2147483647

export const batchExportsRunsListResponseResultsItemRecordsFailedMin = -2147483648
export const batchExportsRunsListResponseResultsItemRecordsFailedMax = 2147483647

export const batchExportsRunsListResponseResultsItemRecordsTotalCountMin = -2147483648
export const batchExportsRunsListResponseResultsItemRecordsTotalCountMax = 2147483647

export const batchExportsRunsListResponseResultsItemBytesExportedMin = -9223372036854776000
export const batchExportsRunsListResponseResultsItemBytesExportedMax = 9223372036854776000

export const BatchExportsRunsListResponse = /* @__PURE__ */ zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                status: zod
                    .enum([
                        'Cancelled',
                        'Completed',
                        'ContinuedAsNew',
                        'Failed',
                        'FailedRetryable',
                        'FailedBilling',
                        'Terminated',
                        'TimedOut',
                        'Running',
                        'Starting',
                    ])
                    .describe(
                        '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                    )
                    .describe(
                        'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                    ),
                records_completed: zod
                    .number()
                    .min(batchExportsRunsListResponseResultsItemRecordsCompletedMin)
                    .max(batchExportsRunsListResponseResultsItemRecordsCompletedMax)
                    .nullish()
                    .describe('The number of records that have been exported.'),
                records_failed: zod
                    .number()
                    .min(batchExportsRunsListResponseResultsItemRecordsFailedMin)
                    .max(batchExportsRunsListResponseResultsItemRecordsFailedMax)
                    .nullish()
                    .describe(
                        'The number of records that failed downstream processing (e.g. hog function execution errors).'
                    ),
                latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExportRun was created.'),
                finished_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                last_updated_at: zod.iso
                    .datetime({})
                    .describe('The timestamp at which this BatchExportRun was last updated.'),
                records_total_count: zod
                    .number()
                    .min(batchExportsRunsListResponseResultsItemRecordsTotalCountMin)
                    .max(batchExportsRunsListResponseResultsItemRecordsTotalCountMax)
                    .nullish()
                    .describe('The total count of records that should be exported in this BatchExportRun.'),
                bytes_exported: zod
                    .number()
                    .min(batchExportsRunsListResponseResultsItemBytesExportedMin)
                    .max(batchExportsRunsListResponseResultsItemBytesExportedMax)
                    .nullish()
                    .describe('The number of bytes that have been exported in this BatchExportRun.'),
                batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
            })
            .describe('Serializer for a BatchExportRun model.')
    ),
})

export const batchExportsRunsRetrieveResponseRecordsCompletedMin = -2147483648
export const batchExportsRunsRetrieveResponseRecordsCompletedMax = 2147483647

export const batchExportsRunsRetrieveResponseRecordsFailedMin = -2147483648
export const batchExportsRunsRetrieveResponseRecordsFailedMax = 2147483647

export const batchExportsRunsRetrieveResponseRecordsTotalCountMin = -2147483648
export const batchExportsRunsRetrieveResponseRecordsTotalCountMax = 2147483647

export const batchExportsRunsRetrieveResponseBytesExportedMin = -9223372036854776000
export const batchExportsRunsRetrieveResponseBytesExportedMax = 9223372036854776000

export const BatchExportsRunsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        status: zod
            .enum([
                'Cancelled',
                'Completed',
                'ContinuedAsNew',
                'Failed',
                'FailedRetryable',
                'FailedBilling',
                'Terminated',
                'TimedOut',
                'Running',
                'Starting',
            ])
            .describe(
                '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
            )
            .describe(
                'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
            ),
        records_completed: zod
            .number()
            .min(batchExportsRunsRetrieveResponseRecordsCompletedMin)
            .max(batchExportsRunsRetrieveResponseRecordsCompletedMax)
            .nullish()
            .describe('The number of records that have been exported.'),
        records_failed: zod
            .number()
            .min(batchExportsRunsRetrieveResponseRecordsFailedMin)
            .max(batchExportsRunsRetrieveResponseRecordsFailedMax)
            .nullish()
            .describe('The number of records that failed downstream processing (e.g. hog function execution errors).'),
        latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
        data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
        data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
        cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExportRun was created.'),
        finished_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExportRun was last updated.'),
        records_total_count: zod
            .number()
            .min(batchExportsRunsRetrieveResponseRecordsTotalCountMin)
            .max(batchExportsRunsRetrieveResponseRecordsTotalCountMax)
            .nullish()
            .describe('The total count of records that should be exported in this BatchExportRun.'),
        bytes_exported: zod
            .number()
            .min(batchExportsRunsRetrieveResponseBytesExportedMin)
            .max(batchExportsRunsRetrieveResponseBytesExportedMax)
            .nullish()
            .describe('The number of bytes that have been exported in this BatchExportRun.'),
        batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
        backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
    })
    .describe('Serializer for a BatchExportRun model.')

/**
 * Cancel a batch export run.
 */
export const batchExportsRunsCancelCreateBodyRecordsCompletedMin = -2147483648
export const batchExportsRunsCancelCreateBodyRecordsCompletedMax = 2147483647

export const batchExportsRunsCancelCreateBodyRecordsFailedMin = -2147483648
export const batchExportsRunsCancelCreateBodyRecordsFailedMax = 2147483647

export const batchExportsRunsCancelCreateBodyRecordsTotalCountMin = -2147483648
export const batchExportsRunsCancelCreateBodyRecordsTotalCountMax = 2147483647

export const batchExportsRunsCancelCreateBodyBytesExportedMin = -9223372036854776000
export const batchExportsRunsCancelCreateBodyBytesExportedMax = 9223372036854776000

export const BatchExportsRunsCancelCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum([
                'Cancelled',
                'Completed',
                'ContinuedAsNew',
                'Failed',
                'FailedRetryable',
                'FailedBilling',
                'Terminated',
                'TimedOut',
                'Running',
                'Starting',
            ])
            .describe(
                '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
            )
            .describe(
                'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
            ),
        records_completed: zod
            .number()
            .min(batchExportsRunsCancelCreateBodyRecordsCompletedMin)
            .max(batchExportsRunsCancelCreateBodyRecordsCompletedMax)
            .nullish()
            .describe('The number of records that have been exported.'),
        records_failed: zod
            .number()
            .min(batchExportsRunsCancelCreateBodyRecordsFailedMin)
            .max(batchExportsRunsCancelCreateBodyRecordsFailedMax)
            .nullish()
            .describe('The number of records that failed downstream processing (e.g. hog function execution errors).'),
        latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
        data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
        data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
        cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
        finished_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
        records_total_count: zod
            .number()
            .min(batchExportsRunsCancelCreateBodyRecordsTotalCountMin)
            .max(batchExportsRunsCancelCreateBodyRecordsTotalCountMax)
            .nullish()
            .describe('The total count of records that should be exported in this BatchExportRun.'),
        bytes_exported: zod
            .number()
            .min(batchExportsRunsCancelCreateBodyBytesExportedMin)
            .max(batchExportsRunsCancelCreateBodyBytesExportedMax)
            .nullish()
            .describe('The number of bytes that have been exported in this BatchExportRun.'),
        backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
    })
    .describe('Serializer for a BatchExportRun model.')

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export const batchExportsRunsRetryCreateBodyRecordsCompletedMin = -2147483648
export const batchExportsRunsRetryCreateBodyRecordsCompletedMax = 2147483647

export const batchExportsRunsRetryCreateBodyRecordsFailedMin = -2147483648
export const batchExportsRunsRetryCreateBodyRecordsFailedMax = 2147483647

export const batchExportsRunsRetryCreateBodyRecordsTotalCountMin = -2147483648
export const batchExportsRunsRetryCreateBodyRecordsTotalCountMax = 2147483647

export const batchExportsRunsRetryCreateBodyBytesExportedMin = -9223372036854776000
export const batchExportsRunsRetryCreateBodyBytesExportedMax = 9223372036854776000

export const BatchExportsRunsRetryCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum([
                'Cancelled',
                'Completed',
                'ContinuedAsNew',
                'Failed',
                'FailedRetryable',
                'FailedBilling',
                'Terminated',
                'TimedOut',
                'Running',
                'Starting',
            ])
            .describe(
                '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
            )
            .describe(
                'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
            ),
        records_completed: zod
            .number()
            .min(batchExportsRunsRetryCreateBodyRecordsCompletedMin)
            .max(batchExportsRunsRetryCreateBodyRecordsCompletedMax)
            .nullish()
            .describe('The number of records that have been exported.'),
        records_failed: zod
            .number()
            .min(batchExportsRunsRetryCreateBodyRecordsFailedMin)
            .max(batchExportsRunsRetryCreateBodyRecordsFailedMax)
            .nullish()
            .describe('The number of records that failed downstream processing (e.g. hog function execution errors).'),
        latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
        data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
        data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
        cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
        finished_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
        records_total_count: zod
            .number()
            .min(batchExportsRunsRetryCreateBodyRecordsTotalCountMin)
            .max(batchExportsRunsRetryCreateBodyRecordsTotalCountMax)
            .nullish()
            .describe('The total count of records that should be exported in this BatchExportRun.'),
        bytes_exported: zod
            .number()
            .min(batchExportsRunsRetryCreateBodyBytesExportedMin)
            .max(batchExportsRunsRetryCreateBodyBytesExportedMax)
            .nullish()
            .describe('The number of bytes that have been exported in this BatchExportRun.'),
        backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
    })
    .describe('Serializer for a BatchExportRun model.')

export const batchExportsRetrieve2ResponseLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsRetrieve2ResponseLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsRetrieve2ResponseLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsRetrieve2ResponseLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsRetrieve2ResponseLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsRetrieve2ResponseLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsRetrieve2ResponseLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsRetrieve2ResponseLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsRetrieve2ResponseOffsetDayMin = 0
export const batchExportsRetrieve2ResponseOffsetDayMax = 6

export const batchExportsRetrieve2ResponseOffsetHourMin = 0
export const batchExportsRetrieve2ResponseOffsetHourMax = 23

export const BatchExportsRetrieve2Response = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number().describe('The team this belongs to.'),
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was last updated.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        latest_runs: zod.array(
            zod
                .object({
                    id: zod.uuid(),
                    status: zod
                        .enum([
                            'Cancelled',
                            'Completed',
                            'ContinuedAsNew',
                            'Failed',
                            'FailedRetryable',
                            'FailedBilling',
                            'Terminated',
                            'TimedOut',
                            'Running',
                            'Starting',
                        ])
                        .describe(
                            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        )
                        .describe(
                            'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        ),
                    records_completed: zod
                        .number()
                        .min(batchExportsRetrieve2ResponseLatestRunsItemRecordsCompletedMin)
                        .max(batchExportsRetrieve2ResponseLatestRunsItemRecordsCompletedMax)
                        .nullish()
                        .describe('The number of records that have been exported.'),
                    records_failed: zod
                        .number()
                        .min(batchExportsRetrieve2ResponseLatestRunsItemRecordsFailedMin)
                        .max(batchExportsRetrieve2ResponseLatestRunsItemRecordsFailedMax)
                        .nullish()
                        .describe(
                            'The number of records that failed downstream processing (e.g. hog function execution errors).'
                        ),
                    latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                    data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                    data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                    cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                    created_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was created.'),
                    finished_at: zod.iso
                        .datetime({})
                        .nullish()
                        .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                    last_updated_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was last updated.'),
                    records_total_count: zod
                        .number()
                        .min(batchExportsRetrieve2ResponseLatestRunsItemRecordsTotalCountMin)
                        .max(batchExportsRetrieve2ResponseLatestRunsItemRecordsTotalCountMax)
                        .nullish()
                        .describe('The total count of records that should be exported in this BatchExportRun.'),
                    bytes_exported: zod
                        .number()
                        .min(batchExportsRetrieve2ResponseLatestRunsItemBytesExportedMin)
                        .max(batchExportsRetrieve2ResponseLatestRunsItemBytesExportedMax)
                        .nullish()
                        .describe('The number of bytes that have been exported in this BatchExportRun.'),
                    batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                    backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                })
                .describe('Serializer for a BatchExportRun model.')
        ),
        hogql_query: zod.string().optional(),
        schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsRetrieve2ResponseOffsetDayMin)
            .max(batchExportsRetrieve2ResponseOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsRetrieve2ResponseOffsetHourMin)
            .max(batchExportsRetrieve2ResponseOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsUpdate2BodyOffsetDayMin = 0
export const batchExportsUpdate2BodyOffsetDayMax = 6

export const batchExportsUpdate2BodyOffsetHourMin = 0
export const batchExportsUpdate2BodyOffsetHourMax = 23

export const BatchExportsUpdate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsUpdate2BodyOffsetDayMin)
            .max(batchExportsUpdate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsUpdate2BodyOffsetHourMin)
            .max(batchExportsUpdate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsUpdate2ResponseLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsUpdate2ResponseLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsUpdate2ResponseLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsUpdate2ResponseLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsUpdate2ResponseLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsUpdate2ResponseLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsUpdate2ResponseLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsUpdate2ResponseLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsUpdate2ResponseOffsetDayMin = 0
export const batchExportsUpdate2ResponseOffsetDayMax = 6

export const batchExportsUpdate2ResponseOffsetHourMin = 0
export const batchExportsUpdate2ResponseOffsetHourMax = 23

export const BatchExportsUpdate2Response = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number().describe('The team this belongs to.'),
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was last updated.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        latest_runs: zod.array(
            zod
                .object({
                    id: zod.uuid(),
                    status: zod
                        .enum([
                            'Cancelled',
                            'Completed',
                            'ContinuedAsNew',
                            'Failed',
                            'FailedRetryable',
                            'FailedBilling',
                            'Terminated',
                            'TimedOut',
                            'Running',
                            'Starting',
                        ])
                        .describe(
                            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        )
                        .describe(
                            'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        ),
                    records_completed: zod
                        .number()
                        .min(batchExportsUpdate2ResponseLatestRunsItemRecordsCompletedMin)
                        .max(batchExportsUpdate2ResponseLatestRunsItemRecordsCompletedMax)
                        .nullish()
                        .describe('The number of records that have been exported.'),
                    records_failed: zod
                        .number()
                        .min(batchExportsUpdate2ResponseLatestRunsItemRecordsFailedMin)
                        .max(batchExportsUpdate2ResponseLatestRunsItemRecordsFailedMax)
                        .nullish()
                        .describe(
                            'The number of records that failed downstream processing (e.g. hog function execution errors).'
                        ),
                    latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                    data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                    data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                    cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                    created_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was created.'),
                    finished_at: zod.iso
                        .datetime({})
                        .nullish()
                        .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                    last_updated_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was last updated.'),
                    records_total_count: zod
                        .number()
                        .min(batchExportsUpdate2ResponseLatestRunsItemRecordsTotalCountMin)
                        .max(batchExportsUpdate2ResponseLatestRunsItemRecordsTotalCountMax)
                        .nullish()
                        .describe('The total count of records that should be exported in this BatchExportRun.'),
                    bytes_exported: zod
                        .number()
                        .min(batchExportsUpdate2ResponseLatestRunsItemBytesExportedMin)
                        .max(batchExportsUpdate2ResponseLatestRunsItemBytesExportedMax)
                        .nullish()
                        .describe('The number of bytes that have been exported in this BatchExportRun.'),
                    batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                    backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                })
                .describe('Serializer for a BatchExportRun model.')
        ),
        hogql_query: zod.string().optional(),
        schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsUpdate2ResponseOffsetDayMin)
            .max(batchExportsUpdate2ResponseOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsUpdate2ResponseOffsetHourMin)
            .max(batchExportsUpdate2ResponseOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsPartialUpdate2BodyOffsetDayMin = 0
export const batchExportsPartialUpdate2BodyOffsetDayMax = 6

export const batchExportsPartialUpdate2BodyOffsetHourMin = 0
export const batchExportsPartialUpdate2BodyOffsetHourMax = 23

export const BatchExportsPartialUpdate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().optional().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .optional()
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .optional()
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsPartialUpdate2BodyOffsetDayMin)
            .max(batchExportsPartialUpdate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsPartialUpdate2BodyOffsetHourMin)
            .max(batchExportsPartialUpdate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsPartialUpdate2ResponseLatestRunsItemRecordsCompletedMin = -2147483648
export const batchExportsPartialUpdate2ResponseLatestRunsItemRecordsCompletedMax = 2147483647

export const batchExportsPartialUpdate2ResponseLatestRunsItemRecordsFailedMin = -2147483648
export const batchExportsPartialUpdate2ResponseLatestRunsItemRecordsFailedMax = 2147483647

export const batchExportsPartialUpdate2ResponseLatestRunsItemRecordsTotalCountMin = -2147483648
export const batchExportsPartialUpdate2ResponseLatestRunsItemRecordsTotalCountMax = 2147483647

export const batchExportsPartialUpdate2ResponseLatestRunsItemBytesExportedMin = -9223372036854776000
export const batchExportsPartialUpdate2ResponseLatestRunsItemBytesExportedMax = 9223372036854776000

export const batchExportsPartialUpdate2ResponseOffsetDayMin = 0
export const batchExportsPartialUpdate2ResponseOffsetDayMax = 6

export const batchExportsPartialUpdate2ResponseOffsetHourMin = 0
export const batchExportsPartialUpdate2ResponseOffsetHourMax = 23

export const BatchExportsPartialUpdate2Response = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number().describe('The team this belongs to.'),
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        created_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was created.'),
        last_updated_at: zod.iso.datetime({}).describe('The timestamp at which this BatchExport was last updated.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        latest_runs: zod.array(
            zod
                .object({
                    id: zod.uuid(),
                    status: zod
                        .enum([
                            'Cancelled',
                            'Completed',
                            'ContinuedAsNew',
                            'Failed',
                            'FailedRetryable',
                            'FailedBilling',
                            'Terminated',
                            'TimedOut',
                            'Running',
                            'Starting',
                        ])
                        .describe(
                            '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        )
                        .describe(
                            'The status of this run.\n\n* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `ContinuedAsNew` - Continued As New\n* `Failed` - Failed\n* `FailedRetryable` - Failed Retryable\n* `FailedBilling` - Failed Billing\n* `Terminated` - Terminated\n* `TimedOut` - Timedout\n* `Running` - Running\n* `Starting` - Starting'
                        ),
                    records_completed: zod
                        .number()
                        .min(batchExportsPartialUpdate2ResponseLatestRunsItemRecordsCompletedMin)
                        .max(batchExportsPartialUpdate2ResponseLatestRunsItemRecordsCompletedMax)
                        .nullish()
                        .describe('The number of records that have been exported.'),
                    records_failed: zod
                        .number()
                        .min(batchExportsPartialUpdate2ResponseLatestRunsItemRecordsFailedMin)
                        .max(batchExportsPartialUpdate2ResponseLatestRunsItemRecordsFailedMax)
                        .nullish()
                        .describe(
                            'The number of records that failed downstream processing (e.g. hog function execution errors).'
                        ),
                    latest_error: zod.string().nullish().describe('The latest error that occurred during this run.'),
                    data_interval_start: zod.iso.datetime({}).nullish().describe('The start of the data interval.'),
                    data_interval_end: zod.iso.datetime({}).describe('The end of the data interval.'),
                    cursor: zod.string().nullish().describe('An opaque cursor that may be used to resume.'),
                    created_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was created.'),
                    finished_at: zod.iso
                        .datetime({})
                        .nullish()
                        .describe('The timestamp at which this BatchExportRun finished, successfully or not.'),
                    last_updated_at: zod.iso
                        .datetime({})
                        .describe('The timestamp at which this BatchExportRun was last updated.'),
                    records_total_count: zod
                        .number()
                        .min(batchExportsPartialUpdate2ResponseLatestRunsItemRecordsTotalCountMin)
                        .max(batchExportsPartialUpdate2ResponseLatestRunsItemRecordsTotalCountMax)
                        .nullish()
                        .describe('The total count of records that should be exported in this BatchExportRun.'),
                    bytes_exported: zod
                        .number()
                        .min(batchExportsPartialUpdate2ResponseLatestRunsItemBytesExportedMin)
                        .max(batchExportsPartialUpdate2ResponseLatestRunsItemBytesExportedMax)
                        .nullish()
                        .describe('The number of bytes that have been exported in this BatchExportRun.'),
                    batch_export: zod.uuid().describe('The BatchExport this run belongs to.'),
                    backfill: zod.uuid().nullish().describe('The backfill this run belongs to.'),
                })
                .describe('Serializer for a BatchExportRun model.')
        ),
        hogql_query: zod.string().optional(),
        schema: zod.unknown().nullable().describe('A schema of custom fields to select when exporting data.'),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsPartialUpdate2ResponseOffsetDayMin)
            .max(batchExportsPartialUpdate2ResponseOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsPartialUpdate2ResponseOffsetHourMin)
            .max(batchExportsPartialUpdate2ResponseOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

/**
 * Pause a BatchExport.
 */
export const batchExportsPauseCreate2BodyOffsetDayMin = 0
export const batchExportsPauseCreate2BodyOffsetDayMax = 6

export const batchExportsPauseCreate2BodyOffsetHourMin = 0
export const batchExportsPauseCreate2BodyOffsetHourMax = 23

export const BatchExportsPauseCreate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsPauseCreate2BodyOffsetDayMin)
            .max(batchExportsPauseCreate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsPauseCreate2BodyOffsetHourMin)
            .max(batchExportsPauseCreate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRunTestStepCreate2BodyOffsetDayMin = 0
export const batchExportsRunTestStepCreate2BodyOffsetDayMax = 6

export const batchExportsRunTestStepCreate2BodyOffsetHourMin = 0
export const batchExportsRunTestStepCreate2BodyOffsetHourMax = 23

export const BatchExportsRunTestStepCreate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsRunTestStepCreate2BodyOffsetDayMin)
            .max(batchExportsRunTestStepCreate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsRunTestStepCreate2BodyOffsetHourMin)
            .max(batchExportsRunTestStepCreate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

/**
 * Unpause a BatchExport.
 */
export const batchExportsUnpauseCreate2BodyOffsetDayMin = 0
export const batchExportsUnpauseCreate2BodyOffsetDayMax = 6

export const batchExportsUnpauseCreate2BodyOffsetHourMin = 0
export const batchExportsUnpauseCreate2BodyOffsetHourMax = 23

export const BatchExportsUnpauseCreate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsUnpauseCreate2BodyOffsetDayMin)
            .max(batchExportsUnpauseCreate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsUnpauseCreate2BodyOffsetHourMin)
            .max(batchExportsUnpauseCreate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRunTestStepNewCreate2BodyOffsetDayMin = 0
export const batchExportsRunTestStepNewCreate2BodyOffsetDayMax = 6

export const batchExportsRunTestStepNewCreate2BodyOffsetHourMin = 0
export const batchExportsRunTestStepNewCreate2BodyOffsetHourMax = 23

export const BatchExportsRunTestStepNewCreate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('A human-readable name for this BatchExport.'),
        model: zod
            .union([
                zod
                    .enum(['events', 'persons', 'sessions'])
                    .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Which model this BatchExport is exporting.\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .object({
                type: zod
                    .enum([
                        'S3',
                        'Snowflake',
                        'Postgres',
                        'Redshift',
                        'BigQuery',
                        'Databricks',
                        'AzureBlob',
                        'Workflows',
                        'HTTP',
                        'NoOp',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop'
                    ),
                config: zod
                    .unknown()
                    .optional()
                    .describe(
                        'A JSON field to store all configuration parameters required to access a BatchExportDestination.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod.number().nullish(),
            })
            .describe('Serializer for an BatchExportDestination model.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether this BatchExport is paused or not.'),
        last_paused_at: zod.iso
            .datetime({})
            .nullish()
            .describe('The timestamp at which this BatchExport was last paused.'),
        start_at: zod.iso
            .datetime({})
            .nullish()
            .describe("Time before which any Batch Export runs won't be triggered."),
        end_at: zod.iso.datetime({}).nullish().describe("Time after which any Batch Export runs won't be triggered."),
        hogql_query: zod.string().optional(),
        filters: zod.unknown().nullish(),
        timezone: zod.union([zod.string(), zod.literal(null)]).nullish(),
        offset_day: zod
            .number()
            .min(batchExportsRunTestStepNewCreate2BodyOffsetDayMin)
            .max(batchExportsRunTestStepNewCreate2BodyOffsetDayMax)
            .nullish(),
        offset_hour: zod
            .number()
            .min(batchExportsRunTestStepNewCreate2BodyOffsetHourMin)
            .max(batchExportsRunTestStepNewCreate2BodyOffsetHourMax)
            .nullish(),
    })
    .describe('Serializer for a BatchExport model.')
