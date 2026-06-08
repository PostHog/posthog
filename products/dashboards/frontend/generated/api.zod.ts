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
    dashboard_filters: zod.unknown().optional(),
    tags: zod.array(zod.string().max(dashboardTemplatesCreateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().optional(),
    variables: zod.unknown().optional(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesCreateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('\* `team` - Only team\n\* `global` - Global\n\* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesCreateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesUpdateBodyTemplateNameMax = 400

export const dashboardTemplatesUpdateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesUpdateBodyTagsItemMax = 255

export const dashboardTemplatesUpdateBodyImageUrlMax = 8201

export const dashboardTemplatesUpdateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesUpdateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesUpdateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesUpdateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().optional(),
    tags: zod.array(zod.string().max(dashboardTemplatesUpdateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().optional(),
    variables: zod.unknown().optional(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesUpdateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('\* `team` - Only team\n\* `global` - Global\n\* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesUpdateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesPartialUpdateBodyTemplateNameMax = 400

export const dashboardTemplatesPartialUpdateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesPartialUpdateBodyTagsItemMax = 255

export const dashboardTemplatesPartialUpdateBodyImageUrlMax = 8201

export const dashboardTemplatesPartialUpdateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesPartialUpdateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesPartialUpdateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesPartialUpdateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().optional(),
    tags: zod.array(zod.string().max(dashboardTemplatesPartialUpdateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().optional(),
    variables: zod.unknown().optional(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesPartialUpdateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('\* `team` - Only team\n\* `global` - Global\n\* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesPartialUpdateBodyAvailabilityContextsItemMax))
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
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
        .describe(
            '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
        ),
    user_uuid: zod.uuid(),
})

export const dashboardsUpdateBodyNameMax = 400

export const dashboardsUpdateBodyDeleteInsightsDefault = false

export const DashboardsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
 * Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile).
 */
export const DashboardsCopyTileCreateBody = /* @__PURE__ */ zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

/**
 * Add a markdown text tile to a dashboard.

Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
or annotations between insight tiles to give the dashboard structure.
 */
export const dashboardsCreateTextTileCreateBodyBodyMax = 4000

export const dashboardsCreateTextTileCreateBodyColorMax = 400

export const DashboardsCreateTextTileCreateBody = /* @__PURE__ */ zod.object({
    body: zod
        .string()
        .min(1)
        .max(dashboardsCreateTextTileCreateBodyBodyMax)
        .describe(
            'Markdown body for the text tile. Supports headings, lists, and inline formatting. Useful as a dashboard section heading, divider, or annotation between insights. Max 4000 characters.'
        ),
    layouts: zod
        .object({
            sm: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
            xs: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
        })
        .optional()
        .describe(
            'Optional grid layout per breakpoint. If omitted, the tile is placed at the bottom of the dashboard using the default size. Text tiles typically use a thin full-width banner (e.g. w=12, h=1).'
        ),
    color: zod
        .string()
        .max(dashboardsCreateTextTileCreateBodyColorMax)
        .nullish()
        .describe("Optional accent color name (e.g. 'blue', 'green', 'purple', 'black')."),
})

/**
 * Soft-delete a single tile from a dashboard.

Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
use the dashboard delete endpoint instead.
 */
export const DashboardsDeleteTileBody = /* @__PURE__ */ zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to delete. Use dashboard-get to look up tile IDs.'),
})

export const DashboardsMoveTileCreateBody = /* @__PURE__ */ zod.object({
    to_dashboard: zod.number().describe('Destination dashboard ID.'),
    tile: zod
        .object({
            id: zod.number().describe('Dashboard tile ID to move.'),
        })
        .describe('Tile to move, identified by its dashboard tile ID.'),
})

export const DashboardsMoveTilePartialUpdateBody = /* @__PURE__ */ zod.object({
    to_dashboard: zod.number().optional().describe('Destination dashboard ID.'),
    tile: zod
        .object({
            id: zod.number().describe('Dashboard tile ID to move.'),
        })
        .optional()
        .describe('Tile to move, identified by its dashboard tile ID.'),
})

export const dashboardsReorderTilesCreateBodyLayoutDefault = `preserve`

export const DashboardsReorderTilesCreateBody = /* @__PURE__ */ zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
    layout: zod
        .enum(['preserve', 'two_column', 'full_width'])
        .describe('\* `preserve` - preserve\n\* `two_column` - two_column\n\* `full_width` - full_width')
        .default(dashboardsReorderTilesCreateBodyLayoutDefault)
        .describe(
            "How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height and only repacks positions in the new order. 'two_column' forces a 6-wide × 5-tall grid (two tiles per row). 'full_width' forces each tile to span the full 12-column row at height 5.\n\n\* `preserve` - preserve\n\* `two_column` - two_column\n\* `full_width` - full_width"
        ),
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
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
 * Update the markdown body, layout, or color of an existing text tile on a dashboard.
 */
export const dashboardsUpdateTextTileCreateBodyBodyMax = 4000

export const dashboardsUpdateTextTileCreateBodyColorMax = 400

export const DashboardsUpdateTextTileCreateBody = /* @__PURE__ */ zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to update. Use dashboard-get to look up tile IDs.'),
    body: zod
        .string()
        .min(1)
        .max(dashboardsUpdateTextTileCreateBodyBodyMax)
        .optional()
        .describe('New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.'),
    layouts: zod
        .object({
            sm: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
            xs: zod
                .object({
                    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
                    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
                    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                    h: zod.number().optional().describe('Height in grid rows.'),
                })
                .optional()
                .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
        })
        .optional()
        .describe('New grid layout per breakpoint. Omit to leave the layout unchanged.'),
    color: zod
        .string()
        .max(dashboardsUpdateTextTileCreateBodyColorMax)
        .nullish()
        .describe('New accent color name, empty string or null to clear. Omit to leave unchanged.'),
})

/**
 * Add multiple widget tiles to a dashboard in one atomic request.
 */
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderByDefault = `occurrences`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneStatusDefault = `active`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitDefault = 10
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitMax = 25

export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderByDefault = `start_time`
export const dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderDirectionDefault = `DESC`
export const dashboardsWidgetsBatchCreateBodyWidgetsMax = 10

export const DashboardsWidgetsBatchCreateBody = /* @__PURE__ */ zod
    .object({
        widgets: zod
            .array(
                zod.union([
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemOneNameMax)
                            .nullish()
                            .describe('Optional custom display name for the widget tile.'),
                        description: zod
                            .string()
                            .optional()
                            .describe('Optional markdown description shown when show_description is enabled.'),
                        layouts: zod
                            .object({
                                sm: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe(
                                        'Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'
                                    ),
                                xs: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
                            })
                            .optional()
                            .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                        show_description: zod
                            .boolean()
                            .optional()
                            .describe('Whether to show the description on the dashboard tile.'),
                        widget_type: zod.enum(['error_tracking_list']),
                        config: zod
                            .object({
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneLimitDefault)
                                    .describe('Maximum number of issues to return (page size).'),
                                orderBy: zod
                                    .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
                                    .describe(
                                        '\* `last_seen` - last_seen\n\* `first_seen` - first_seen\n\* `occurrences` - occurrences\n\* `users` - users\n\* `sessions` - sessions'
                                    )
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderByDefault)
                                    .describe(
                                        'Issue ranking column.\n\n\* `first_seen` - first_seen\n\* `last_seen` - last_seen\n\* `occurrences` - occurrences\n\* `sessions` - sessions\n\* `users` - users'
                                    ),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.\n\n\* `ASC` - ASC\n\* `DESC` - DESC'),
                                status: zod
                                    .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
                                    .describe(
                                        '\* `archived` - archived\n\* `active` - active\n\* `resolved` - resolved\n\* `pending_release` - pending_release\n\* `suppressed` - suppressed\n\* `all` - all'
                                    )
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemOneConfigOneStatusDefault)
                                    .describe(
                                        'Issue status filter.\n\n\* `archived` - archived\n\* `active` - active\n\* `resolved` - resolved\n\* `pending_release` - pending_release\n\* `suppressed` - suppressed\n\* `all` - all'
                                    ),
                                assignee: zod
                                    .union([
                                        zod.object({
                                            id: zod
                                                .union([zod.string(), zod.number(), zod.null()])
                                                .describe('User ID or role UUID to filter by.'),
                                            type: zod
                                                .enum(['user', 'role'])
                                                .describe('\* `user` - user\n\* `role` - role')
                                                .describe(
                                                    'Assignee target type: user or role.\n\n\* `user` - user\n\* `role` - role'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Filter by assignee ({type: user|role, id}). Omit for any assignee.'),
                                widgetFilters: zod
                                    .record(
                                        zod.string(),
                                        zod.object({
                                            filterId: zod
                                                .string()
                                                .describe('Filter UUID; must match the widgetFilters map key.'),
                                            propertyName: zod
                                                .string()
                                                .describe('Event property key (for example $environment).'),
                                            optionId: zod
                                                .string()
                                                .describe('Selected option id from the filter definition.'),
                                            operator: zod
                                                .string()
                                                .describe(
                                                    'Property filter operator (for example exact, is_not, icontains).'
                                                ),
                                            value: zod
                                                .unknown()
                                                .optional()
                                                .describe('Filter value as a string, list of strings, or null.'),
                                        })
                                    )
                                    .optional()
                                    .describe(
                                        "Widget filter selections keyed by filter id. Each key must match the entry's filterId. Configure filters in the product UI first, then copy filter id, option id, and property name here."
                                    ),
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod
                                                        .enum(['-14d', '-1h', '-24h', '-30d', '-3h', '-7d', '-90d'])
                                                        .describe(
                                                            '\* `-14d` - -14d\n\* `-1h` - -1h\n\* `-24h` - -24h\n\* `-30d` - -30d\n\* `-3h` - -3h\n\* `-7d` - -7d\n\* `-90d` - -90d'
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Relative lookback window (for example '-7d'). Omit to use the project default range.\n\n\* `-14d` - -14d\n\* `-1h` - -1h\n\* `-24h` - -24h\n\* `-30d` - -30d\n\* `-3h` - -3h\n\* `-7d` - -7d\n\* `-90d` - -90d"
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Relative date range for issues (date_from only on widgets).'),
                                filterTestAccounts: zod
                                    .boolean()
                                    .optional()
                                    .describe('When omitted, follows the project default for filtering test accounts.'),
                            })
                            .describe('Configuration for the error tracking list widget.'),
                    }),
                    zod.object({
                        name: zod
                            .string()
                            .max(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoNameMax)
                            .nullish()
                            .describe('Optional custom display name for the widget tile.'),
                        description: zod
                            .string()
                            .optional()
                            .describe('Optional markdown description shown when show_description is enabled.'),
                        layouts: zod
                            .object({
                                sm: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe(
                                        'Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'
                                    ),
                                xs: zod
                                    .object({
                                        x: zod
                                            .number()
                                            .optional()
                                            .describe('Column position in the dashboard grid (0-indexed).'),
                                        y: zod
                                            .number()
                                            .optional()
                                            .describe('Row position in the dashboard grid (0-indexed).'),
                                        w: zod
                                            .number()
                                            .optional()
                                            .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                        h: zod.number().optional().describe('Height in grid rows.'),
                                    })
                                    .optional()
                                    .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
                            })
                            .optional()
                            .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                        show_description: zod
                            .boolean()
                            .optional()
                            .describe('Whether to show the description on the dashboard tile.'),
                        widget_type: zod.enum(['session_replay_list']),
                        config: zod
                            .object({
                                limit: zod
                                    .number()
                                    .min(1)
                                    .max(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitMax)
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneLimitDefault)
                                    .describe('Maximum number of recordings to return.'),
                                orderBy: zod
                                    .enum([
                                        'activity_score',
                                        'click_count',
                                        'console_error_count',
                                        'duration',
                                        'recording_duration',
                                        'start_time',
                                    ])
                                    .describe(
                                        '\* `activity_score` - activity_score\n\* `click_count` - click_count\n\* `console_error_count` - console_error_count\n\* `duration` - duration\n\* `recording_duration` - recording_duration\n\* `start_time` - start_time'
                                    )
                                    .default(dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderByDefault)
                                    .describe(
                                        'Recording ranking column.\n\n\* `activity_score` - activity_score\n\* `click_count` - click_count\n\* `console_error_count` - console_error_count\n\* `duration` - duration\n\* `recording_duration` - recording_duration\n\* `start_time` - start_time'
                                    ),
                                orderDirection: zod
                                    .enum(['ASC', 'DESC'])
                                    .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
                                    .default(
                                        dashboardsWidgetsBatchCreateBodyWidgetsItemTwoConfigOneOrderDirectionDefault
                                    )
                                    .describe('Sort direction for orderBy.\n\n\* `ASC` - ASC\n\* `DESC` - DESC'),
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([
                                                    zod
                                                        .enum(['-14d', '-1h', '-24h', '-30d', '-3h', '-7d', '-90d'])
                                                        .describe(
                                                            '\* `-14d` - -14d\n\* `-1h` - -1h\n\* `-24h` - -24h\n\* `-30d` - -30d\n\* `-3h` - -3h\n\* `-7d` - -7d\n\* `-90d` - -90d'
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Relative lookback window (for example '-7d'). Omit to use the project default range.\n\n\* `-14d` - -14d\n\* `-1h` - -1h\n\* `-24h` - -24h\n\* `-30d` - -30d\n\* `-3h` - -3h\n\* `-7d` - -7d\n\* `-90d` - -90d"
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Optional relative date range override.'),
                                widgetFilters: zod
                                    .record(
                                        zod.string(),
                                        zod.object({
                                            filterId: zod
                                                .string()
                                                .describe('Filter UUID; must match the widgetFilters map key.'),
                                            propertyName: zod
                                                .string()
                                                .describe('Event property key (for example $environment).'),
                                            optionId: zod
                                                .string()
                                                .describe('Selected option id from the filter definition.'),
                                            operator: zod
                                                .string()
                                                .describe(
                                                    'Property filter operator (for example exact, is_not, icontains).'
                                                ),
                                            value: zod
                                                .unknown()
                                                .optional()
                                                .describe('Filter value as a string, list of strings, or null.'),
                                        })
                                    )
                                    .optional()
                                    .describe(
                                        "Widget filter selections keyed by filter id. Each key must match the entry's filterId. Configure filters in the product UI first, then copy filter id, option id, and property name here."
                                    ),
                                filterTestAccounts: zod
                                    .boolean()
                                    .optional()
                                    .describe('When omitted, follows the project default for filtering test accounts.'),
                            })
                            .describe('Configuration for the session replay list widget.'),
                    }),
                ])
            )
            .min(1)
            .max(dashboardsWidgetsBatchCreateBodyWidgetsMax)
            .describe(
                'Widget tiles to add atomically. Supported widget_type values: error_tracking_list, session_replay_list. Use dashboard-widget-catalog-list for config_schema_hints per type. (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.')

/**
 * Bulk update tags on multiple objects.

PAT access: this action has no ``required_scopes=`` on the decorator —
inheriting viewsets must add ``"bulk_update_tags"`` to their
``scope_object_write_actions`` list to accept personal API keys.
Without that opt-in, ``APIScopePermission`` rejects PAT requests with
"This action does not support personal API key access". Done per-viewset
so granting ``<scope>:write`` for one resource doesn't leak access to
sibling resources that share this mixin.

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
        .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
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
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .optional()
            .describe(
                '\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
            ),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
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
