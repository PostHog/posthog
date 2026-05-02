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
                integration: zod.number().nullish(),
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

/**
 * Create a new backfill for a BatchExport.
 */
export const batchExportsBackfillsCreateBodyTotalRecordsCountMin = -2147483648
export const batchExportsBackfillsCreateBodyTotalRecordsCountMax = 2147483647

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
 * Cancel a batch export backfill.
 */
export const batchExportsBackfillsCancelCreateBodyTotalRecordsCountMin = -2147483648
export const batchExportsBackfillsCancelCreateBodyTotalRecordsCountMax = 2147483647

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

/**
 * Cancel a batch export run.
 */
export const batchExportsRunsCancelCreateBodyRecordsCompletedMin = -2147483648
export const batchExportsRunsCancelCreateBodyRecordsCompletedMax = 2147483647

export const batchExportsRunsCancelCreateBodyRecordsFailedMin = -2147483648
export const batchExportsRunsCancelCreateBodyRecordsFailedMax = 2147483647

export const batchExportsRunsCancelCreateBodyRecordsTotalCountMin = -2147483648
export const batchExportsRunsCancelCreateBodyRecordsTotalCountMax = 2147483647

export const batchExportsRunsCancelCreateBodyBytesExportedMin = -2147483648
export const batchExportsRunsCancelCreateBodyBytesExportedMax = 2147483647

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

export const batchExportsRunsRetryCreateBodyBytesExportedMin = -2147483648
export const batchExportsRunsRetryCreateBodyBytesExportedMax = 2147483647

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
                integration: zod.number().nullish(),
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
                integration: zod.number().nullish(),
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
                integration: zod.number().nullish(),
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
                integration: zod.number().nullish(),
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
                integration: zod.number().nullish(),
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
                integration: zod.number().nullish(),
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
