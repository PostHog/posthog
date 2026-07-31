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

import {
    CreateTableFromUploadApi,
    DataWarehouseSavedQueryApi,
    DataWarehouseSavedQueryColumnAnnotationApi,
    DataWarehouseSavedQueryDraftApi,
    DataWarehouseSavedQueryFolderApi,
    InsightVariableApi,
    OnboardWarehouseTeamRequestApi,
    PatchedDataWarehouseSavedQueryApi,
    PatchedDataWarehouseSavedQueryColumnAnnotationApi,
    PatchedDataWarehouseSavedQueryDraftApi,
    PatchedDataWarehouseSavedQueryFolderApi,
    PatchedInsightVariableApi,
    PatchedQueryTabStateApi,
    PatchedTableApi,
    PatchedViewLinkApi,
    PatchedWarehouseColumnAnnotationApi,
    ProvisionWarehouseRequestApi,
    QueryTabStateApi,
    TableApi,
    ViewLinkApi,
    ViewLinkValidationApi,
    WarehouseColumnAnnotationApi,
} from './api.zod.schemas'

/**
 * Onboard this project onto the organization's existing managed warehouse.
 *
 * Requires a schema name and records the project's membership in the Duckgres control plane.
 * Restricted to organization admins.
 */
export const DataWarehouseOnboardTeamCreateBody = OnboardWarehouseTeamRequestApi

/**
 * Start provisioning a managed warehouse for this organization (shared by all its teams).
 */
export const DataWarehouseProvisionCreateBody = ProvisionWarehouseRequestApi

export const InsightVariablesCreateBody = InsightVariableApi

export const InsightVariablesUpdateBody = InsightVariableApi

export const InsightVariablesPartialUpdateBody = PatchedInsightVariableApi

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateCreateBody = QueryTabStateApi

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateUpdateBody = QueryTabStateApi

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStatePartialUpdateBody = PatchedQueryTabStateApi

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const SavedQueryColumnAnnotationsCreateBody = DataWarehouseSavedQueryColumnAnnotationApi

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const SavedQueryColumnAnnotationsUpdateBody = DataWarehouseSavedQueryColumnAnnotationApi

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const SavedQueryColumnAnnotationsPartialUpdateBody = PatchedDataWarehouseSavedQueryColumnAnnotationApi

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const WarehouseColumnAnnotationsCreateBody = WarehouseColumnAnnotationApi

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const WarehouseColumnAnnotationsUpdateBody = WarehouseColumnAnnotationApi

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const WarehouseColumnAnnotationsPartialUpdateBody = PatchedWarehouseColumnAnnotationApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesCreateBody = DataWarehouseSavedQueryApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesUpdateBody = DataWarehouseSavedQueryApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesPartialUpdateBody = PatchedDataWarehouseSavedQueryApi

/**
 * Return the ancestors of this saved query.
 *
 * By default, we return the immediate parents. The `level` parameter can be used to
 * look further back into the ancestor tree. If `level` overshoots (i.e. points to only
 * ancestors beyond the root), we return an empty list.
 */
export const WarehouseSavedQueriesAncestorsCreateBody = DataWarehouseSavedQueryApi

/**
 * Cancel a running saved query workflow.
 */
export const WarehouseSavedQueriesCancelCreateBody = DataWarehouseSavedQueryApi

/**
 * Return the descendants of this saved query.
 *
 * By default, we return the immediate children. The `level` parameter can be used to
 * look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
 * descendants further than a leaf), we return an empty list.
 */
export const WarehouseSavedQueriesDescendantsCreateBody = DataWarehouseSavedQueryApi

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const WarehouseSavedQueriesMaterializeCreateBody = DataWarehouseSavedQueryApi

/**
 * Undo materialization, revert back to the original view.
 * (i.e. delete the materialized table and the schedule)
 */
export const WarehouseSavedQueriesRevertMaterializationCreateBody = DataWarehouseSavedQueryApi

/**
 * Run this saved query.
 */
export const WarehouseSavedQueriesRunCreateBody = DataWarehouseSavedQueryApi

/**
 * Resume paused materialization schedules for multiple matviews.
 *
 * Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
 * This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export const WarehouseSavedQueriesResumeSchedulesCreateBody = DataWarehouseSavedQueryApi

export const WarehouseSavedQueryDraftsCreateBody = DataWarehouseSavedQueryDraftApi

export const WarehouseSavedQueryDraftsUpdateBody = DataWarehouseSavedQueryDraftApi

export const WarehouseSavedQueryDraftsPartialUpdateBody = PatchedDataWarehouseSavedQueryDraftApi

export const WarehouseSavedQueryFoldersCreateBody = DataWarehouseSavedQueryFolderApi

export const WarehouseSavedQueryFoldersPartialUpdateBody = PatchedDataWarehouseSavedQueryFolderApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesCreateBody = TableApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesUpdateBody = TableApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesPartialUpdateBody = PatchedTableApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesUpdateSchemaCreateBody = TableApi

/**
 * Turn a previously uploaded file into a self-managed warehouse table.
 *
 * The file already sits in PostHog's own bucket (see `upload_file`), so the table points straight
 * at it and is read in place — no import pipeline and no recurring sync, the same shape as a linked
 * S3/GCS bucket. The read location is always derived from the caller's own team, so a client-supplied
 * `upload_id` can only resolve inside that team's folder, and the table carries no credential (reads
 * fall back to the node role, never a user-supplied key).
 * @summary Create a self-managed warehouse table from an uploaded file
 */
export const WarehouseTablesCreateFromUploadCreateBody = CreateTableFromUploadApi

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesFileCreateBody = TableApi

/**
 * Store an uploaded file in object storage so a self-managed table can be created from it.
 *
 * Uploading is a separate first step from `create_from_upload` so the create call stays JSON-only:
 * this returns an `upload_id` the caller passes back to build the table. The file is written under
 * a team-scoped prefix, so a table can only ever read back its own team's uploads.
 * @summary Upload a file for a new self-managed warehouse table
 */
export const WarehouseTablesUploadFileCreateBody = /* @__PURE__ */ zod.object({
    file: zod.instanceof(File).describe('The file to upload.'),
    file_format: zod.enum(['csv', 'json', 'parquet']).describe('How the file will be read when the table is created.'),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkCreateBody = ViewLinkApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkUpdateBody = ViewLinkApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkPartialUpdateBody = PatchedViewLinkApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkValidateCreateBody = ViewLinkValidationApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksCreateBody = ViewLinkApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksUpdateBody = ViewLinkApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksPartialUpdateBody = PatchedViewLinkApi

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksValidateCreateBody = ViewLinkValidationApi
