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

export const batchExportsCreateBodyDestinationOneOneConfigUseVariantTypeDefault = true
export const batchExportsCreateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault = true
export const batchExportsCreateBodyDestinationOneTwoConfigPrefixDefault = ``
export const batchExportsCreateBodyDestinationOneTwoConfigFileFormatDefault = `JSONLines`
export const batchExportsCreateBodyOffsetDayMin = 0
export const batchExportsCreateBodyOffsetDayMax = 6

export const batchExportsCreateBodyOffsetHourMin = 0
export const batchExportsCreateBodyOffsetHourMax = 23

export const BatchExportsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('Human-readable name for the batch export.'),
        model: zod
            .enum(['events', 'persons', 'sessions'])
            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions')
            .optional()
            .describe(
                'Which data model to export (events, persons, sessions).\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .union([
                zod
                    .object({
                        type: zod.enum(['Databricks']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(batchExportsCreateBodyDestinationOneOneConfigUseVariantTypeDefault)
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsCreateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a Databricks batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['AzureBlob']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsCreateBodyDestinationOneTwoConfigPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsCreateBodyDestinationOneTwoConfigFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating an Azure Blob Storage batch-export destination.'),
            ])
            .describe('Destination configuration. Required integration_id is enforced per destination type.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether the batch export is paused.'),
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .string()
            .nullish()
            .describe(
                "IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries."
            ),
        offset_day: zod
            .number()
            .min(batchExportsCreateBodyOffsetDayMin)
            .max(batchExportsCreateBodyOffsetDayMax)
            .nullish()
            .describe('Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).'),
        offset_hour: zod
            .number()
            .min(batchExportsCreateBodyOffsetHourMin)
            .max(batchExportsCreateBodyOffsetHourMax)
            .nullish()
            .describe('Hour-of-day offset (0-23) for daily and weekly intervals.'),
    })
    .describe(
        'Request body for create/partial_update on BatchExportViewSet.\n\nMirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic\n`destination` schema so integration_id is marked required on the types that need\nit. Responses continue to use `BatchExportSerializer`.'
    )

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

export const batchExportsUpdateBodyDestinationOneOneConfigUseVariantTypeDefault = true
export const batchExportsUpdateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault = true
export const batchExportsUpdateBodyDestinationOneTwoConfigPrefixDefault = ``
export const batchExportsUpdateBodyDestinationOneTwoConfigFileFormatDefault = `JSONLines`
export const batchExportsUpdateBodyOffsetDayMin = 0
export const batchExportsUpdateBodyOffsetDayMax = 6

export const batchExportsUpdateBodyOffsetHourMin = 0
export const batchExportsUpdateBodyOffsetHourMax = 23

export const BatchExportsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('Human-readable name for the batch export.'),
        model: zod
            .enum(['events', 'persons', 'sessions'])
            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions')
            .optional()
            .describe(
                'Which data model to export (events, persons, sessions).\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .union([
                zod
                    .object({
                        type: zod.enum(['Databricks']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(batchExportsUpdateBodyDestinationOneOneConfigUseVariantTypeDefault)
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsUpdateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a Databricks batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['AzureBlob']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsUpdateBodyDestinationOneTwoConfigPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsUpdateBodyDestinationOneTwoConfigFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating an Azure Blob Storage batch-export destination.'),
            ])
            .describe('Destination configuration. Required integration_id is enforced per destination type.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether the batch export is paused.'),
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .string()
            .nullish()
            .describe(
                "IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries."
            ),
        offset_day: zod
            .number()
            .min(batchExportsUpdateBodyOffsetDayMin)
            .max(batchExportsUpdateBodyOffsetDayMax)
            .nullish()
            .describe('Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).'),
        offset_hour: zod
            .number()
            .min(batchExportsUpdateBodyOffsetHourMin)
            .max(batchExportsUpdateBodyOffsetHourMax)
            .nullish()
            .describe('Hour-of-day offset (0-23) for daily and weekly intervals.'),
    })
    .describe(
        'Request body for create/partial_update on BatchExportViewSet.\n\nMirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic\n`destination` schema so integration_id is marked required on the types that need\nit. Responses continue to use `BatchExportSerializer`.'
    )

export const batchExportsPartialUpdateBodyDestinationOneOneConfigUseVariantTypeDefault = true
export const batchExportsPartialUpdateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault = true
export const batchExportsPartialUpdateBodyDestinationOneTwoConfigPrefixDefault = ``
export const batchExportsPartialUpdateBodyDestinationOneTwoConfigFileFormatDefault = `JSONLines`
export const batchExportsPartialUpdateBodyOffsetDayMin = 0
export const batchExportsPartialUpdateBodyOffsetDayMax = 6

export const batchExportsPartialUpdateBodyOffsetHourMin = 0
export const batchExportsPartialUpdateBodyOffsetHourMax = 23

export const BatchExportsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().optional().describe('Human-readable name for the batch export.'),
        model: zod
            .enum(['events', 'persons', 'sessions'])
            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions')
            .optional()
            .describe(
                'Which data model to export (events, persons, sessions).\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .union([
                zod
                    .object({
                        type: zod.enum(['Databricks']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(batchExportsPartialUpdateBodyDestinationOneOneConfigUseVariantTypeDefault)
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsPartialUpdateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a Databricks batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['AzureBlob']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsPartialUpdateBodyDestinationOneTwoConfigPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsPartialUpdateBodyDestinationOneTwoConfigFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating an Azure Blob Storage batch-export destination.'),
            ])
            .optional()
            .describe('Destination configuration. Required integration_id is enforced per destination type.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .optional()
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether the batch export is paused.'),
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .string()
            .nullish()
            .describe(
                "IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries."
            ),
        offset_day: zod
            .number()
            .min(batchExportsPartialUpdateBodyOffsetDayMin)
            .max(batchExportsPartialUpdateBodyOffsetDayMax)
            .nullish()
            .describe('Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).'),
        offset_hour: zod
            .number()
            .min(batchExportsPartialUpdateBodyOffsetHourMin)
            .max(batchExportsPartialUpdateBodyOffsetHourMax)
            .nullish()
            .describe('Hour-of-day offset (0-23) for daily and weekly intervals.'),
    })
    .describe(
        'Request body for create/partial_update on BatchExportViewSet.\n\nMirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic\n`destination` schema so integration_id is marked required on the types that need\nit. Responses continue to use `BatchExportSerializer`.'
    )

/**
 * Pause a BatchExport.
 */
export const batchExportsPauseCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault = true
export const batchExportsPauseCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault = true
export const batchExportsPauseCreateBodyDestinationOneConfigOneTwoPrefixDefault = ``
export const batchExportsPauseCreateBodyDestinationOneConfigOneTwoFileFormatDefault = `JSONLines`
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
                        'FileDownload',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    ),
                config: zod
                    .union([
                        zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(batchExportsPauseCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault)
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsPauseCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                        zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsPauseCreateBodyDestinationOneConfigOneTwoPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsPauseCreateBodyDestinationOneConfigOneTwoFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    ])
                    .describe(
                        'Destination-specific configuration. Fields depend on `type`. Credentials for integration-backed destinations (Databricks, AzureBlob) are NOT stored here — they live in the linked Integration. Secret fields are stripped from responses.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod
                    .number()
                    .nullish()
                    .describe(
                        'ID of a team-scoped Integration providing credentials. Required for Databricks and AzureBlob destinations; optional for BigQuery; unused for other types.'
                    ),
            })
            .describe(
                'Serializer for an BatchExportDestination model.\n\nThe `config` field is polymorphic and typed only for destinations that keep\ncredentials in the linked Integration (currently Databricks and AzureBlob).\nOther destination types accept the same JSON shape but without a typed\nOpenAPI schema. Secret fields are stripped from `config` on read.'
            )
            .describe('Destination configuration (type, config, and optional integration).'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
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
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .union([zod.string(), zod.literal(null)])
            .nullish()
            .describe(
                'IANA timezone name controlling daily and weekly interval boundaries. Defaults to UTC.\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        offset_day: zod
            .number()
            .min(batchExportsPauseCreateBodyOffsetDayMin)
            .max(batchExportsPauseCreateBodyOffsetDayMax)
            .nullish()
            .describe(
                "Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday). Only valid when interval is 'week'."
            ),
        offset_hour: zod
            .number()
            .min(batchExportsPauseCreateBodyOffsetHourMin)
            .max(batchExportsPauseCreateBodyOffsetHourMax)
            .nullish()
            .describe(
                "Hour-of-day offset (0-23) for daily and weekly intervals. Only valid when interval is 'day' or 'week'."
            ),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRunTestStepCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault = true
export const batchExportsRunTestStepCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault = true
export const batchExportsRunTestStepCreateBodyDestinationOneConfigOneTwoPrefixDefault = ``
export const batchExportsRunTestStepCreateBodyDestinationOneConfigOneTwoFileFormatDefault = `JSONLines`
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
                        'FileDownload',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    ),
                config: zod
                    .union([
                        zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(
                                        batchExportsRunTestStepCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault
                                    )
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsRunTestStepCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                        zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsRunTestStepCreateBodyDestinationOneConfigOneTwoPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(
                                        batchExportsRunTestStepCreateBodyDestinationOneConfigOneTwoFileFormatDefault
                                    )
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    ])
                    .describe(
                        'Destination-specific configuration. Fields depend on `type`. Credentials for integration-backed destinations (Databricks, AzureBlob) are NOT stored here — they live in the linked Integration. Secret fields are stripped from responses.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod
                    .number()
                    .nullish()
                    .describe(
                        'ID of a team-scoped Integration providing credentials. Required for Databricks and AzureBlob destinations; optional for BigQuery; unused for other types.'
                    ),
            })
            .describe(
                'Serializer for an BatchExportDestination model.\n\nThe `config` field is polymorphic and typed only for destinations that keep\ncredentials in the linked Integration (currently Databricks and AzureBlob).\nOther destination types accept the same JSON shape but without a typed\nOpenAPI schema. Secret fields are stripped from `config` on read.'
            )
            .describe('Destination configuration (type, config, and optional integration).'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
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
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .union([zod.string(), zod.literal(null)])
            .nullish()
            .describe(
                'IANA timezone name controlling daily and weekly interval boundaries. Defaults to UTC.\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        offset_day: zod
            .number()
            .min(batchExportsRunTestStepCreateBodyOffsetDayMin)
            .max(batchExportsRunTestStepCreateBodyOffsetDayMax)
            .nullish()
            .describe(
                "Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday). Only valid when interval is 'week'."
            ),
        offset_hour: zod
            .number()
            .min(batchExportsRunTestStepCreateBodyOffsetHourMin)
            .max(batchExportsRunTestStepCreateBodyOffsetHourMax)
            .nullish()
            .describe(
                "Hour-of-day offset (0-23) for daily and weekly intervals. Only valid when interval is 'day' or 'week'."
            ),
    })
    .describe('Serializer for a BatchExport model.')

/**
 * Unpause a BatchExport.
 */
export const batchExportsUnpauseCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault = true
export const batchExportsUnpauseCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault = true
export const batchExportsUnpauseCreateBodyDestinationOneConfigOneTwoPrefixDefault = ``
export const batchExportsUnpauseCreateBodyDestinationOneConfigOneTwoFileFormatDefault = `JSONLines`
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
                        'FileDownload',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    ),
                config: zod
                    .union([
                        zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(
                                        batchExportsUnpauseCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault
                                    )
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsUnpauseCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                        zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsUnpauseCreateBodyDestinationOneConfigOneTwoPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsUnpauseCreateBodyDestinationOneConfigOneTwoFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    ])
                    .describe(
                        'Destination-specific configuration. Fields depend on `type`. Credentials for integration-backed destinations (Databricks, AzureBlob) are NOT stored here — they live in the linked Integration. Secret fields are stripped from responses.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod
                    .number()
                    .nullish()
                    .describe(
                        'ID of a team-scoped Integration providing credentials. Required for Databricks and AzureBlob destinations; optional for BigQuery; unused for other types.'
                    ),
            })
            .describe(
                'Serializer for an BatchExportDestination model.\n\nThe `config` field is polymorphic and typed only for destinations that keep\ncredentials in the linked Integration (currently Databricks and AzureBlob).\nOther destination types accept the same JSON shape but without a typed\nOpenAPI schema. Secret fields are stripped from `config` on read.'
            )
            .describe('Destination configuration (type, config, and optional integration).'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
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
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .union([zod.string(), zod.literal(null)])
            .nullish()
            .describe(
                'IANA timezone name controlling daily and weekly interval boundaries. Defaults to UTC.\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        offset_day: zod
            .number()
            .min(batchExportsUnpauseCreateBodyOffsetDayMin)
            .max(batchExportsUnpauseCreateBodyOffsetDayMax)
            .nullish()
            .describe(
                "Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday). Only valid when interval is 'week'."
            ),
        offset_hour: zod
            .number()
            .min(batchExportsUnpauseCreateBodyOffsetHourMin)
            .max(batchExportsUnpauseCreateBodyOffsetHourMax)
            .nullish()
            .describe(
                "Hour-of-day offset (0-23) for daily and weekly intervals. Only valid when interval is 'day' or 'week'."
            ),
    })
    .describe('Serializer for a BatchExport model.')

export const batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault = true
export const batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault = true
export const batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneTwoPrefixDefault = ``
export const batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneTwoFileFormatDefault = `JSONLines`
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
                        'FileDownload',
                    ])
                    .describe(
                        '* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    )
                    .describe(
                        'A choice of supported BatchExportDestination types.\n\n* `S3` - S3\n* `Snowflake` - Snowflake\n* `Postgres` - Postgres\n* `Redshift` - Redshift\n* `BigQuery` - Bigquery\n* `Databricks` - Databricks\n* `AzureBlob` - Azure Blob\n* `Workflows` - Workflows\n* `HTTP` - Http\n* `NoOp` - Noop\n* `FileDownload` - File Download'
                    ),
                config: zod
                    .union([
                        zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(
                                        batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneOneUseVariantTypeDefault
                                    )
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneOneUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                        zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(
                                        batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneTwoPrefixDefault
                                    )
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.literal(null),
                                    ])
                                    .nullish()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(
                                        batchExportsRunTestStepNewCreateBodyDestinationOneConfigOneTwoFileFormatDefault
                                    )
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    ])
                    .describe(
                        'Destination-specific configuration. Fields depend on `type`. Credentials for integration-backed destinations (Databricks, AzureBlob) are NOT stored here — they live in the linked Integration. Secret fields are stripped from responses.'
                    ),
                integration: zod.number().nullish().describe('The integration for this destination.'),
                integration_id: zod
                    .number()
                    .nullish()
                    .describe(
                        'ID of a team-scoped Integration providing credentials. Required for Databricks and AzureBlob destinations; optional for BigQuery; unused for other types.'
                    ),
            })
            .describe(
                'Serializer for an BatchExportDestination model.\n\nThe `config` field is polymorphic and typed only for destinations that keep\ncredentials in the linked Integration (currently Databricks and AzureBlob).\nOther destination types accept the same JSON shape but without a typed\nOpenAPI schema. Secret fields are stripped from `config` on read.'
            )
            .describe('Destination configuration (type, config, and optional integration).'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
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
        hogql_query: zod
            .string()
            .optional()
            .describe('Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases.'),
        filters: zod.unknown().nullish(),
        timezone: zod
            .union([zod.string(), zod.literal(null)])
            .nullish()
            .describe(
                'IANA timezone name controlling daily and weekly interval boundaries. Defaults to UTC.\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        offset_day: zod
            .number()
            .min(batchExportsRunTestStepNewCreateBodyOffsetDayMin)
            .max(batchExportsRunTestStepNewCreateBodyOffsetDayMax)
            .nullish()
            .describe(
                "Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday). Only valid when interval is 'week'."
            ),
        offset_hour: zod
            .number()
            .min(batchExportsRunTestStepNewCreateBodyOffsetHourMin)
            .max(batchExportsRunTestStepNewCreateBodyOffsetHourMax)
            .nullish()
            .describe(
                "Hour-of-day offset (0-23) for daily and weekly intervals. Only valid when interval is 'day' or 'week'."
            ),
    })
    .describe('Serializer for a BatchExport model.')
