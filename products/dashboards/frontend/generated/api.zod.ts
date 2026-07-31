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
    AddDashboardWidgetsBatchRequestOpenApiApi,
    BulkUpdateTagsRequestApi,
    CopyDashboardTemplateApi,
    CopyDashboardTileRequestApi,
    CreateTextTileRequestApi,
    DashboardApi,
    DashboardCollaboratorApi,
    DashboardTemplateApi,
    DataColorThemeApi,
    DeleteTileRequestApi,
    MoveTileRequestApi,
    PatchedDashboardTemplateApi,
    PatchedDataColorThemeApi,
    PatchedMoveTileRequestApi,
    PatchedPatchedDashboardOpenApiApi,
    PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi,
    ReorderTilesRequestApi,
    UpdateTextTileRequestApi,
} from './api.zod.schemas'

export const DashboardTemplatesCreateBody = DashboardTemplateApi

export const DashboardTemplatesUpdateBody = DashboardTemplateApi

export const DashboardTemplatesPartialUpdateBody = PatchedDashboardTemplateApi

/**
 * Creates a new team-scoped template in the **target** project (URL) from a **team-scoped** source template in the same organization. Global and feature-flag templates return 400. Cross-organization or inaccessible sources return 404. Source and destination projects must differ (400 if equal). Conflicting `template_name` values on the destination are auto-suffixed with `(copy)`, `(copy 2)`, …
 * @summary Copy a team template to this project
 */
export const DashboardTemplatesCopyBetweenProjectsCreateBody = CopyDashboardTemplateApi

export const DashboardsCreateBody = DashboardApi

export const DashboardsCollaboratorsCreateBody = DashboardCollaboratorApi

export const DashboardsUpdateBody = DashboardApi

export const DashboardsPartialUpdateBody = PatchedPatchedDashboardOpenApiApi

/**
 * Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile).
 */
export const DashboardsCopyTileCreateBody = CopyDashboardTileRequestApi

/**
 * Add a markdown text tile to a dashboard.
 *
 * Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
 * or annotations between insight tiles to give the dashboard structure.
 */
export const DashboardsCreateTextTileCreateBody = CreateTextTileRequestApi

/**
 * Soft-delete a single tile from a dashboard.
 *
 * Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
 * object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
 * use the dashboard delete endpoint instead.
 */
export const DashboardsDeleteTileBody = DeleteTileRequestApi

export const DashboardsMoveTileCreateBody = MoveTileRequestApi

export const DashboardsMoveTilePartialUpdateBody = PatchedMoveTileRequestApi

export const DashboardsReorderTilesCreateBody = ReorderTilesRequestApi

/**
 * Update the markdown body, layout, or color of an existing text tile on a dashboard.
 */
export const DashboardsUpdateTextTileCreateBody = UpdateTextTileRequestApi

/**
 * Add multiple widget tiles to a dashboard in one atomic request.
 */
export const DashboardsWidgetsBatchCreateBody = AddDashboardWidgetsBatchRequestOpenApiApi

/**
 * Update the settings of existing widgets in place, atomically — config, name, and description.
 *
 * Each entry targets a widget by its tile_id and reuses the same write path as the dashboard PATCH endpoint.
 * The widget_type is immutable. This edits widget settings only (config, name, description); tile placement
 * (layouts, show_description) is a dashboard concern — use the dashboard PATCH endpoint or reorder_tiles for
 * that. All updates succeed or fail together. To add new widgets, use the widgets/batch POST endpoint; to
 * remove one, use delete_tile.
 */
export const DashboardsUpdateWidgetsBatchBody = PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const DashboardsBulkUpdateTagsCreateBody = BulkUpdateTagsRequestApi

export const DashboardsCreateFromTemplateJsonCreateBody = DashboardApi

/**
 * Creates an unlisted dashboard from template by tag.
 * Enforces uniqueness (one per tag per team).
 * Returns 409 if unlisted dashboard with this tag already exists.
 */
export const DashboardsCreateUnlistedDashboardCreateBody = DashboardApi

export const DataColorThemesCreateBody = DataColorThemeApi

export const DataColorThemesUpdateBody = DataColorThemeApi

export const DataColorThemesPartialUpdateBody = PatchedDataColorThemeApi
