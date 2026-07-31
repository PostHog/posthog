/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    BatchExportApi,
    BatchExportBackfillApi,
    BatchExportRequestApi,
    BatchExportRunApi,
    CreateFileDownloadRequestApi,
    FileDownloadBatchExportOnDemandApi,
    PatchedBatchExportRequestApi,
} from './api.zod.schemas'

export const BatchExportsCreateBody = BatchExportRequestApi

/**
 * Create a new backfill for a BatchExport.
 */
export const BatchExportsBackfillsCreateBody = BatchExportBackfillApi

/**
 * Cancel a batch export backfill.
 */
export const BatchExportsBackfillsCancelCreateBody = BatchExportBackfillApi

/**
 * Cancel a batch export run.
 */
export const BatchExportsRunsCancelCreateBody = BatchExportRunApi

/**
 * Retry a batch export run.
 *
 * We use the same underlying mechanism as when backfilling a batch export, as retrying
 * a run is the same as backfilling one run.
 */
export const BatchExportsRunsRetryCreateBody = BatchExportRunApi

export const BatchExportsUpdateBody = BatchExportRequestApi

export const BatchExportsPartialUpdateBody = PatchedBatchExportRequestApi

/**
 * Pause a BatchExport.
 */
export const BatchExportsPauseCreateBody = BatchExportApi

export const BatchExportsRunTestStepCreateBody = BatchExportApi

/**
 * Unpause a BatchExport.
 */
export const BatchExportsUnpauseCreateBody = BatchExportApi

export const BatchExportsRunTestStepNewCreateBody = BatchExportApi

/**
 * Create and start a batch export on demand run to download a file.
 */
export const FileDownloadBatchExportsCreateBody = CreateFileDownloadRequestApi

/**
 * Cancel an ongoing file-download batch export.
 */
export const FileDownloadBatchExportsCancelCreateBody = FileDownloadBatchExportOnDemandApi
