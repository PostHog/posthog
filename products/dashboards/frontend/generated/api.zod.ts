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

export const dashboardTemplatesCreateBodyTemplateNameMax = 400

export const dashboardTemplatesCreateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesCreateBodyTagsItemMax = 255

export const dashboardTemplatesCreateBodyImageUrlMax = 8201

export const dashboardTemplatesCreateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesCreateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesCreateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesCreateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesCreateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesCreateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesCreateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

/**
 * Creates a new team-scoped template in the **target** project (URL) from a **team-scoped** source template in the same organization. Global and feature-flag templates return 400. Cross-organization or inaccessible sources return 404. Source and destination projects must differ (400 if equal). Conflicting `template_name` values on the destination are auto-suffixed with `(copy)`, `(copy 2)`, …
 * @summary Copy a team template to this project
 */
export const DashboardTemplatesCopyBetweenProjectsCreateBody = /* @__PURE__ */ zod.object({
    source_template_id: zod
        .uuid()
        .describe(
            'UUID of a team-scoped template in the same organization. Global and feature-flag templates cannot be copied with this endpoint.'
        ),
})

export const dashboardsCreateBodyNameMax = 400

export const dashboardsCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsCollaboratorsCreateBody = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    user_uuid: zod.uuid(),
})

/**
 * Create a new password for the sharing configuration.
 */
export const DashboardsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const DashboardsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const dashboardsUpdateBodyNameMax = 400

export const dashboardsUpdateBodyDeleteInsightsDefault = false

export const DashboardsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsPartialUpdateBodyNameMax = 400

export const dashboardsPartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsPartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Generate AI analysis comparing before/after dashboard refresh.
Expects cache_key in request body pointing to the stored 'before' state.
 */
export const dashboardsAnalyzeRefreshResultCreateBodyNameMax = 400

export const dashboardsAnalyzeRefreshResultCreateBodyDeleteInsightsDefault = false

export const DashboardsAnalyzeRefreshResultCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsAnalyzeRefreshResultCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsAnalyzeRefreshResultCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Copy an existing dashboard tile to another dashboard (insight or text card; new tile row).
 */
export const DashboardsCopyTileCreateBody = /* @__PURE__ */ zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

export const dashboardsMoveTilePartialUpdateBodyNameMax = 400

export const dashboardsMoveTilePartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsMoveTilePartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsMoveTilePartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsMoveTilePartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsReorderTilesCreateBody = /* @__PURE__ */ zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
})

/**
 * Snapshot the current dashboard state (from cache) for AI analysis.
Returns a cache_key representing the 'before' state, to be used with analyze_refresh_result.
 */
export const dashboardsSnapshotCreateBodyNameMax = 400

export const dashboardsSnapshotCreateBodyDeleteInsightsDefault = false

export const DashboardsSnapshotCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsSnapshotCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsSnapshotCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const dashboardsBulkUpdateTagsCreateBodyIdsMax = 500

export const DashboardsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(dashboardsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('* `add` - add\n* `remove` - remove\n* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n* `add` - add\n* `remove` - remove\n* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

export const dashboardsCreateFromTemplateJsonCreateBodyNameMax = 400

export const dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateFromTemplateJsonCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateFromTemplateJsonCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
export const dashboardsCreateUnlistedDashboardCreateBodyNameMax = 400

export const dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateUnlistedDashboardCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateUnlistedDashboardCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dataColorThemesCreateBodyNameMax = 100

export const DataColorThemesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataColorThemesCreateBodyNameMax),
    colors: zod.unknown().optional(),
})

export const dataColorThemesUpdateBodyNameMax = 100

export const DataColorThemesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataColorThemesUpdateBodyNameMax),
    colors: zod.unknown().optional(),
})

export const dataColorThemesPartialUpdateBodyNameMax = 100

export const DataColorThemesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataColorThemesPartialUpdateBodyNameMax).optional(),
    colors: zod.unknown().optional(),
})
