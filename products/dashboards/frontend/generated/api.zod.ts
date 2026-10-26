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
                .enum(['team', 'organization', 'global', 'feature_flag'])
                .describe(
                    '\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global\n\* `feature_flag` - Feature Flag'
                ),
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
                .enum(['team', 'organization', 'global', 'feature_flag'])
                .describe(
                    '\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global\n\* `feature_flag` - Feature Flag'
                ),
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
                .enum(['team', 'organization', 'global', 'feature_flag'])
                .describe(
                    '\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global\n\* `feature_flag` - Feature Flag'
                ),
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

export const dashboardsCreateBodyBreakdownColorsItemColorTokenRegExp = new RegExp('^preset-[1-9][0-9]\*$')
export const dashboardsCreateBodyGroupsTitleMax = 200

export const dashboardsCreateBodyGroupTitlesMaxOne = 200

export const dashboardsCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsCreateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        groups: zod
            .record(
                zod.string(),
                zod.object({
                    title: zod
                        .string()
                        .max(dashboardsCreateBodyGroupsTitleMax)
                        .optional()
                        .describe(
                            'Heading for the group. When it is blank or omitted, the heading shows the number of tiles.'
                        ),
                    collapsed: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether the group starts closed. Defaults to false. When a viewer opens or closes the group, their browser keeps that choice and it wins over this default. A closed group loads its tiles when a viewer opens it.'
                        ),
                    color: zod
                        .union([
                            zod
                                .enum(['blue', 'purple', 'green', 'yellow', 'orange', 'red'])
                                .describe(
                                    '\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Color of a dot before the group heading. Null or omitted shows no dot.\n\n\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                        ),
                })
            )
            .nullish()
            .describe(
                "Settings for tile groups, keyed by the tiles' group_key. Each group shows as a band of its tiles under a heading that viewers can open and close. Viewers who do not have bands yet see only the group title above its tiles. A write replaces the whole map. Send an empty object or null to remove all group settings."
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsCreateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                'Deprecated: use groups. Titles for tile groups, keyed by group_key. A write replaces all titles and keeps the other group settings. Send an empty object or null to clear titles. Do not send it with groups.'
            ),
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

export const dashboardsUpdateBodyNameMax = 400

export const dashboardsUpdateBodyBreakdownColorsItemColorTokenRegExp = new RegExp('^preset-[1-9][0-9]\*$')
export const dashboardsUpdateBodyGroupsTitleMax = 200

export const dashboardsUpdateBodyGroupTitlesMaxOne = 200

export const dashboardsUpdateBodyDeleteInsightsDefault = false

export const DashboardsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsUpdateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        groups: zod
            .record(
                zod.string(),
                zod.object({
                    title: zod
                        .string()
                        .max(dashboardsUpdateBodyGroupsTitleMax)
                        .optional()
                        .describe(
                            'Heading for the group. When it is blank or omitted, the heading shows the number of tiles.'
                        ),
                    collapsed: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether the group starts closed. Defaults to false. When a viewer opens or closes the group, their browser keeps that choice and it wins over this default. A closed group loads its tiles when a viewer opens it.'
                        ),
                    color: zod
                        .union([
                            zod
                                .enum(['blue', 'purple', 'green', 'yellow', 'orange', 'red'])
                                .describe(
                                    '\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Color of a dot before the group heading. Null or omitted shows no dot.\n\n\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                        ),
                })
            )
            .nullish()
            .describe(
                "Settings for tile groups, keyed by the tiles' group_key. Each group shows as a band of its tiles under a heading that viewers can open and close. Viewers who do not have bands yet see only the group title above its tiles. A write replaces the whole map. Send an empty object or null to remove all group settings."
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsUpdateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                'Deprecated: use groups. Titles for tile groups, keyed by group_key. A write replaces all titles and keeps the other group settings. Send an empty object or null to clear titles. Do not send it with groups.'
            ),
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

export const dashboardsPartialUpdateBodyBreakdownColorsItemColorTokenRegExp = new RegExp('^preset-[1-9][0-9]\*$')
export const dashboardsPartialUpdateBodyGroupsTitleMax = 200

export const dashboardsPartialUpdateBodyGroupTitlesMaxOne = 200

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMin = 0
export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMax = 11

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneYMin = 0

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneWMax = 12

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMin = 0
export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMax = 11

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneYMin = 0

export const dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneWMax = 12

export const dashboardsPartialUpdateBodyTilesItemGroupKeyMax = 100

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneNotebookShortIdOneMax = 128

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitDefault = 25
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitMax = 50

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemKeyMax = 400

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemLabelOneMax = 400

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemValueOneItemOneMax = 4000

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemValueOneMax = 100

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemValueTwoMax = 4000

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneMax = 20

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderByDefault = `occurrences`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeStatusDefault = `active`

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderByDefault = `start_time`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveOrderByDefault = `created_at`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveStatusDefault = `all`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneSevenLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneSevenLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightLimitDefault = 50
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightLimitMax = 100

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightOrderByDefault = `latest`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightWrapLinesDefault = false
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightTimezoneDefault = `UTC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineLimitDefault = 10
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineLimitMax = 25

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineStatusDefault = `all`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineChannelDefault = `all`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineAssigneesMax = 100

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineSearchDefault = ``
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineSearchMax = 200

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineSavedViewIdOneMax = 12

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneGroupByOneMax = 200

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemLabelMax = 40

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemMetricNameMax = 200

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemQuantileOneExclusiveMin = 0
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemQuantileOneExclusiveMax = 1

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersItemKeyMax = 200

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersItemOpDefault = `eq`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersItemValueMax = 400

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersMax = 5

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsMax = 6

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneOrderByColumnDefault = 0
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneOrderByColumnMin = 0

export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneOrderDirectionDefault = `DESC`
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneLimitDefault = 25
export const dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneLimitMax = 100

export const dashboardsPartialUpdateBodyTilesItemWidgetOneNameMax = 400

export const dashboardsPartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        filters: zod
            .object({
                date_from: zod
                    .string()
                    .nullish()
                    .describe(
                        "Dashboard-level start of the date range, e.g. '-30d', '-7d', or an ISO date. Applies to all tiles."
                    ),
                date_to: zod
                    .string()
                    .nullish()
                    .describe(
                        "Dashboard-level end of the date range, e.g. '-1d' or an ISO date. Null\/omitted means up to now."
                    ),
                properties: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Dashboard-level property filters applied to every tile (PostHog property filter group).'
                    ),
            })
            .describe(
                "OpenAPI-only shape for a dashboard's filters object (agents\/MCP).\n\nDocuments the dashboard-level filters that act as the single source of truth for the\ndashboard's tiles. Runtime persistence reads the raw ``filters`` dict from the request body, so\nextra keys are accepted, but these are the ones agents should set."
            )
            .optional()
            .describe(
                'Dashboard-level filters (date range and properties) applied across all tiles as the source of truth.'
            ),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsPartialUpdateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.string()).optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard.'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        groups: zod
            .record(
                zod.string(),
                zod.object({
                    title: zod
                        .string()
                        .max(dashboardsPartialUpdateBodyGroupsTitleMax)
                        .optional()
                        .describe(
                            'Heading for the group. When it is blank or omitted, the heading shows the number of tiles.'
                        ),
                    collapsed: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether the group starts closed. Defaults to false. When a viewer opens or closes the group, their browser keeps that choice and it wins over this default. A closed group loads its tiles when a viewer opens it.'
                        ),
                    color: zod
                        .union([
                            zod
                                .enum(['blue', 'purple', 'green', 'yellow', 'orange', 'red'])
                                .describe(
                                    '\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Color of a dot before the group heading. Null or omitted shows no dot.\n\n\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                        ),
                })
            )
            .nullish()
            .describe(
                "Settings for tile groups, keyed by the tiles' group_key. Each group shows as a band of its tiles under a heading that viewers can open and close. Viewers who do not have bands yet see only the group title above its tiles. A write replaces the whole map. Send an empty object or null to remove all group settings."
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsPartialUpdateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                'Deprecated: use groups. Titles for tile groups, keyed by group_key. A write replaces all titles and keeps the other group settings. Send an empty object or null to clear titles. Do not send it with groups.'
            ),
        tiles: zod
            .array(
                zod.object({
                    id: zod.number().optional().describe('Dashboard tile ID to update.'),
                    layouts: zod
                        .object({
                            sm: zod
                                .object({
                                    x: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMin)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneXMax)
                                        .describe('Column position in the dashboard grid (0-indexed).'),
                                    y: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneYMin)
                                        .describe('Row position in the dashboard grid (0-indexed).'),
                                    w: zod
                                        .number()
                                        .min(1)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneSmOneWMax)
                                        .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                    h: zod.number().min(1).describe('Height in grid rows.'),
                                })
                                .describe(
                                    "Layout for the standard (desktop) breakpoint. The grid is 12 columns wide. A write replaces the tile's whole layout and the dashboard reads desktop placement from this box, so send it whenever you send layouts."
                                ),
                            xs: zod
                                .object({
                                    x: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMin)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneXMax)
                                        .describe('Column position in the dashboard grid (0-indexed).'),
                                    y: zod
                                        .number()
                                        .min(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneYMin)
                                        .describe('Row position in the dashboard grid (0-indexed).'),
                                    w: zod
                                        .number()
                                        .min(1)
                                        .max(dashboardsPartialUpdateBodyTilesItemLayoutsOneXsOneWMax)
                                        .describe('Width in grid columns. The desktop grid is 12 columns wide.'),
                                    h: zod.number().min(1).describe('Height in grid rows.'),
                                })
                                .optional()
                                .describe(
                                    'Layout for the small (mobile) breakpoint, on a 1-column grid. The dashboard derives this layout from the sm order and heights, so a stored xs box does not change what renders.'
                                ),
                        })
                        .optional()
                        .describe(
                            "Grid position and size per breakpoint. Works for every tile type, including insight tiles. A write replaces the tile's whole layout, so send a complete sm box rather than the one value you want to change. Boxes are stored as sent and overlaps are not resolved, so send sm boxes that do not overlap, and include every tile you move in the same request."
                        ),
                    show_description: zod
                        .boolean()
                        .optional()
                        .describe(
                            "Whether to show the tile's description underneath its title on the dashboard. Works for every tile type. The description itself is unaffected and still comes from the tile's insight, text, or widget content — this only toggles whether it renders on the dashboard."
                        ),
                    group_key: zod
                        .string()
                        .max(dashboardsPartialUpdateBodyTilesItemGroupKeyMax)
                        .nullish()
                        .describe(
                            "Key that puts this tile in a group with the other tiles that have the same key on this dashboard. Set the group's title and style in the dashboard's groups. Null or an empty string removes the tile from its group."
                        ),
                    badge: zod
                        .union([
                            zod
                                .enum(['winner', 'cheeky-hog'])
                                .describe('\* `winner` - Winner\n\* `cheeky-hog` - Cheeky hog'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Badge on the tile. winner shows a crown in the top left corner, for example to mark the best tile in a group. cheeky-hog shows a hedgehog when a person hovers over the tile. Null removes the badge. More than one tile in a group can have the winner badge.\n\n\* `winner` - Winner\n\* `cheeky-hog` - Cheeky hog'
                        ),
                    widget: zod
                        .object({
                            id: zod
                                .uuid()
                                .optional()
                                .describe('Existing widget row ID when updating a widget tile via dashboard PATCH.'),
                            widget_type: zod
                                .enum([
                                    'activity_events_list',
                                    'canvas_app',
                                    'conversations_recent_tickets',
                                    'error_tracking_list',
                                    'experiment_results',
                                    'experiments_list',
                                    'logs_list',
                                    'metrics_table',
                                    'notebook_widget',
                                    'session_replay_list',
                                    'survey_results',
                                ])
                                .describe(
                                    '\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `metrics_table` - Metrics Table\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                                )
                                .optional()
                                .describe(
                                    'Widget type identifier (cannot be changed on update).\n\n\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `metrics_table` - Metrics Table\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                                ),
                            config: zod
                                .union([
                                    zod.object({
                                        notebookShortId: zod
                                            .union([
                                                zod
                                                    .string()
                                                    .min(1)
                                                    .max(
                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneNotebookShortIdOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Source notebook short ID.'),
                                        snapshotId: zod
                                            .union([zod.uuid(), zod.null()])
                                            .optional()
                                            .describe(
                                                "Immutable notebook widget snapshot. Add one from a notebook widget's menu."
                                            ),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                        widgetFilters: zod
                                            .union([
                                                zod.record(
                                                    zod.string(),
                                                    zod.object({
                                                        filterId: zod.string().min(1),
                                                        propertyName: zod.string().min(1),
                                                        optionId: zod.string().min(1),
                                                        operator: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'icontains',
                                                            'not_icontains',
                                                            'starts_with',
                                                            'not_starts_with',
                                                            'ends_with',
                                                            'not_ends_with',
                                                            'regex',
                                                            'not_regex',
                                                            'gt',
                                                            'gte',
                                                            'lt',
                                                            'lte',
                                                            'is_set',
                                                            'is_not_set',
                                                            'is_date_exact',
                                                            'is_date_before',
                                                            'is_date_after',
                                                            'between',
                                                            'not_between',
                                                            'min',
                                                            'max',
                                                            'in',
                                                            'not_in',
                                                            'is_cleaned_path_exact',
                                                            'is_cleaned_path_not_exact',
                                                            'flag_evaluates_to',
                                                            'semver_eq',
                                                            'semver_neq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_tilde',
                                                            'semver_caret',
                                                            'semver_wildcard',
                                                            'icontains_multi',
                                                            'not_icontains_multi',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoLimitDefault
                                            )
                                            .describe('Maximum number of events to return.'),
                                        eventName: zod
                                            .union([zod.string().min(1), zod.null()])
                                            .optional()
                                            .describe(
                                                'Limit the feed to a single event name. Omit or null for all events.'
                                            ),
                                        properties: zod
                                            .union([
                                                zod
                                                    .array(
                                                        zod.object({
                                                            key: zod
                                                                .string()
                                                                .min(1)
                                                                .max(
                                                                    dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemKeyMax
                                                                ),
                                                            label: zod
                                                                .union([
                                                                    zod
                                                                        .string()
                                                                        .max(
                                                                            dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemLabelOneMax
                                                                        ),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum(['event', 'person']),
                                                            value: zod
                                                                .union([
                                                                    zod
                                                                        .array(
                                                                            zod.union([
                                                                                zod
                                                                                    .string()
                                                                                    .max(
                                                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemValueOneItemOneMax
                                                                                    ),
                                                                                zod.number(),
                                                                                zod.boolean(),
                                                                            ])
                                                                        )
                                                                        .max(
                                                                            dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemValueOneMax
                                                                        ),
                                                                    zod
                                                                        .string()
                                                                        .max(
                                                                            dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneItemValueTwoMax
                                                                        ),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        })
                                                    )
                                                    .max(
                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneTwoPropertiesOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Event and person property filters, matching Activity > Explore events.'
                                            ),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                        widgetFilters: zod
                                            .union([
                                                zod.record(
                                                    zod.string(),
                                                    zod.object({
                                                        filterId: zod.string().min(1),
                                                        propertyName: zod.string().min(1),
                                                        optionId: zod.string().min(1),
                                                        operator: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'icontains',
                                                            'not_icontains',
                                                            'starts_with',
                                                            'not_starts_with',
                                                            'ends_with',
                                                            'not_ends_with',
                                                            'regex',
                                                            'not_regex',
                                                            'gt',
                                                            'gte',
                                                            'lt',
                                                            'lte',
                                                            'is_set',
                                                            'is_not_set',
                                                            'is_date_exact',
                                                            'is_date_before',
                                                            'is_date_after',
                                                            'between',
                                                            'not_between',
                                                            'min',
                                                            'max',
                                                            'in',
                                                            'not_in',
                                                            'is_cleaned_path_exact',
                                                            'is_cleaned_path_not_exact',
                                                            'flag_evaluates_to',
                                                            'semver_eq',
                                                            'semver_neq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_tilde',
                                                            'semver_caret',
                                                            'semver_wildcard',
                                                            'icontains_multi',
                                                            'not_icontains_multi',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeLimitDefault
                                            )
                                            .describe('Maximum number of issues to return.'),
                                        orderBy: zod
                                            .enum([
                                                'last_seen',
                                                'first_seen',
                                                'occurrences',
                                                'users',
                                                'sessions',
                                                'severity',
                                            ])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderByDefault
                                            )
                                            .describe('Issue ranking column.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderBy.'),
                                        status: zod
                                            .enum([
                                                'archived',
                                                'active',
                                                'resolved',
                                                'pending_release',
                                                'suppressed',
                                                'all',
                                            ])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneThreeStatusDefault
                                            )
                                            .describe('Issue status filter.'),
                                        assignee: zod
                                            .union([
                                                zod.object({
                                                    id: zod.union([zod.string(), zod.number()]),
                                                    type: zod.enum(['user', 'role']),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Filter by assignee ({type: user|role, id}). Omit for any assignee.'
                                            ),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
                                        widgetFilters: zod
                                            .union([
                                                zod.record(
                                                    zod.string(),
                                                    zod.object({
                                                        filterId: zod.string().min(1),
                                                        propertyName: zod.string().min(1),
                                                        optionId: zod.string().min(1),
                                                        operator: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'icontains',
                                                            'not_icontains',
                                                            'starts_with',
                                                            'not_starts_with',
                                                            'ends_with',
                                                            'not_ends_with',
                                                            'regex',
                                                            'not_regex',
                                                            'gt',
                                                            'gte',
                                                            'lt',
                                                            'lte',
                                                            'is_set',
                                                            'is_not_set',
                                                            'is_date_exact',
                                                            'is_date_before',
                                                            'is_date_after',
                                                            'between',
                                                            'not_between',
                                                            'min',
                                                            'max',
                                                            'in',
                                                            'not_in',
                                                            'is_cleaned_path_exact',
                                                            'is_cleaned_path_not_exact',
                                                            'flag_evaluates_to',
                                                            'semver_eq',
                                                            'semver_neq',
                                                            'semver_gt',
                                                            'semver_gte',
                                                            'semver_lt',
                                                            'semver_lte',
                                                            'semver_tilde',
                                                            'semver_caret',
                                                            'semver_wildcard',
                                                            'icontains_multi',
                                                            'not_icontains_multi',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .optional(),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourLimitDefault
                                            )
                                            .describe('Maximum number of recordings to return.'),
                                        orderBy: zod
                                            .enum([
                                                'start_time',
                                                'activity_score',
                                                'recording_duration',
                                                'duration',
                                                'click_count',
                                                'console_error_count',
                                            ])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderByDefault
                                            )
                                            .describe('Recording ranking column.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFourOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderBy.'),
                                        savedFilterId: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                'short_id of a saved session replay filter to refine the recordings shown. When set, the saved filter owns the date range and property filters; only orderBy, orderDirection, and limit still apply. Combine with collectionId to filter within a collection.'
                                            ),
                                        collectionId: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                'short_id of a session replay collection to scope the widget to its pinned recordings. Combine with savedFilterId or property filters to narrow within the collection; orderBy, orderDirection, and limit still apply.'
                                            ),
                                    }),
                                    zod.object({
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveLimitDefault
                                            )
                                            .describe('Maximum number of experiments to return.'),
                                        orderBy: zod
                                            .enum(['created_at', 'name', 'start_date'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveOrderByDefault
                                            )
                                            .describe('Experiment list sort column.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderBy.'),
                                        status: zod
                                            .enum(['draft', 'running', 'paused', 'exposure_frozen', 'stopped', 'all'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneFiveStatusDefault
                                            )
                                            .describe('Experiment status filter.'),
                                        createdBy: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Filter by creator (user id). Omit for any creator.'),
                                    }),
                                    zod.object({
                                        experimentId: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Experiment to show results for. Null until the user picks one in the widget settings.'
                                            ),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe("Null or omitted means all time (the survey's full lifetime)."),
                                        surveyId: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Survey to show performance stats and recent responses for. Null until the user picks one.'
                                            ),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneSevenLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneSevenLimitDefault
                                            )
                                            .describe('Maximum number of recent responses to return.'),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightLimitDefault
                                            )
                                            .describe('Maximum number of log lines to return.'),
                                        orderBy: zod
                                            .enum(['latest', 'earliest'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightOrderByDefault
                                            )
                                            .describe('Sort by newest (latest) or oldest (earliest) first.'),
                                        severityLevels: zod
                                            .array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal']))
                                            .optional()
                                            .describe(
                                                'Only show logs at these severity levels. Empty shows all levels.'
                                            ),
                                        serviceNames: zod
                                            .array(zod.string())
                                            .optional()
                                            .describe('Only show logs from these services. Empty shows all services.'),
                                        wrapLines: zod
                                            .boolean()
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightWrapLinesDefault
                                            )
                                            .describe(
                                                'Wrap long log lines instead of truncating them to a single row.'
                                            ),
                                        timezone: zod
                                            .enum(['UTC', 'local'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneEightTimezoneDefault
                                            )
                                            .describe(
                                                "Render log timestamps in UTC or in each viewer's local timezone."
                                            ),
                                        savedViewId: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe(
                                                'short_id of a saved logs view to use as the source. When set, the saved view owns the date range, severity, service, and property filters; only orderBy and limit still apply.'
                                            ),
                                    }),
                                    zod.object({
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineLimitDefault
                                            )
                                            .describe('Maximum number of tickets to return.'),
                                        status: zod
                                            .enum(['new', 'open', 'pending', 'on_hold', 'resolved', 'all'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineStatusDefault
                                            )
                                            .describe('Ticket status filter.'),
                                        priorities: zod
                                            .array(zod.enum(['low', 'medium', 'high', 'critical']))
                                            .optional()
                                            .describe(
                                                'Only show tickets with these priorities. Empty shows all priorities.'
                                            ),
                                        channel: zod
                                            .enum(['widget', 'email', 'slack', 'teams', 'github', 'all'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineChannelDefault
                                            )
                                            .describe('Ticket channel filter.'),
                                        assignees: zod
                                            .array(
                                                zod.union([
                                                    zod.enum(['me', 'unassigned']),
                                                    zod.object({
                                                        id: zod.union([zod.string(), zod.number()]),
                                                        type: zod.enum(['user', 'role']),
                                                    }),
                                                ])
                                            )
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineAssigneesMax)
                                            .optional()
                                            .describe(
                                                "Only show tickets assigned to these users or roles. 'me' means the requesting user and 'unassigned' means tickets without an assignment. Empty shows all assignees."
                                            ),
                                        search: zod
                                            .string()
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineSearchMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineSearchDefault
                                            )
                                            .describe(
                                                'Search requester name or email, ticket subject, message text, or ticket number.'
                                            ),
                                        savedViewId: zod
                                            .union([
                                                zod
                                                    .string()
                                                    .max(
                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneNineSavedViewIdOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'short_id of a saved Support view to use as the source. When set, the saved view owns the ticket filters; the widget still sorts by most recently updated and applies its limit.'
                                            ),
                                    }),
                                    zod.object({
                                        canvasId: zod
                                            .union([zod.uuid(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Canvas to render in the tile. Null until the user picks one in the widget settings.'
                                            ),
                                    }),
                                    zod.object({
                                        dateRange: zod
                                            .union([
                                                zod.object({
                                                    date_from: zod
                                                        .union([
                                                            zod.enum([
                                                                '-1M',
                                                                '-30M',
                                                                '-1h',
                                                                '-3h',
                                                                '-24h',
                                                                '-7d',
                                                                '-14d',
                                                                '-30d',
                                                                '-90d',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .optional(),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        groupBy: zod
                                            .union([
                                                zod
                                                    .string()
                                                    .min(1)
                                                    .max(
                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneGroupByOneMax
                                                    ),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Label that makes one row per value, e.g. `http.route`. Null until the user sets it.'
                                            ),
                                        columns: zod
                                            .array(
                                                zod.object({
                                                    label: zod
                                                        .string()
                                                        .min(1)
                                                        .max(
                                                            dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemLabelMax
                                                        )
                                                        .describe('Column header, e.g. `Requests\/s`.'),
                                                    metricName: zod
                                                        .string()
                                                        .min(1)
                                                        .max(
                                                            dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemMetricNameMax
                                                        )
                                                        .describe('Name of the metric this column reads.'),
                                                    aggregation: zod
                                                        .enum([
                                                            'rate',
                                                            'increase',
                                                            'sum',
                                                            'avg',
                                                            'min',
                                                            'max',
                                                            'histogram_quantile',
                                                        ])
                                                        .describe(
                                                            'How each time bucket of a row is computed. `rate` and `increase` read counters.'
                                                        ),
                                                    quantile: zod
                                                        .union([
                                                            zod
                                                                .number()
                                                                .gt(
                                                                    dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemQuantileOneExclusiveMin
                                                                )
                                                                .lt(
                                                                    dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemQuantileOneExclusiveMax
                                                                ),
                                                            zod.null(),
                                                        ])
                                                        .optional()
                                                        .describe(
                                                            'Required for `histogram_quantile`, e.g. 0.95 for p95.'
                                                        ),
                                                    filters: zod
                                                        .array(
                                                            zod.object({
                                                                key: zod
                                                                    .string()
                                                                    .min(1)
                                                                    .max(
                                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersItemKeyMax
                                                                    )
                                                                    .describe(
                                                                        'Label key to filter on, e.g. `http.response.status_code`.'
                                                                    ),
                                                                op: zod
                                                                    .enum(['eq', 'neq', 'regex', 'not_regex'])
                                                                    .default(
                                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersItemOpDefault
                                                                    )
                                                                    .describe('How the label value is compared.'),
                                                                value: zod
                                                                    .string()
                                                                    .max(
                                                                        dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersItemValueMax
                                                                    )
                                                                    .describe(
                                                                        'Label value, or a regular expression for `regex` and `not_regex`.'
                                                                    ),
                                                            })
                                                        )
                                                        .max(
                                                            dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsItemFiltersMax
                                                        )
                                                        .optional()
                                                        .describe(
                                                            'Label filters for this column only, e.g. 5xx status codes for an errors column.'
                                                        ),
                                                })
                                            )
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneColumnsMax)
                                            .optional()
                                            .describe(
                                                "One metric per column. Each row shows the column's average over the date range and a sparkline."
                                            ),
                                        interval: zod
                                            .union([
                                                zod.enum(['minute', 'minute_5', 'minute_15', 'hour', 'day']),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe(
                                                'Time between the points of the full charts that open from a row. Null picks one from the date range. The table sparklines always use at most 30 points.'
                                            ),
                                        orderByColumn: zod
                                            .number()
                                            .min(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneOrderByColumnMin
                                            )
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneOrderByColumnDefault
                                            )
                                            .describe('Index of the column that sorts the rows.'),
                                        orderDirection: zod
                                            .enum(['ASC', 'DESC'])
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneOrderDirectionDefault
                                            )
                                            .describe('Sort direction for orderByColumn.'),
                                        limit: zod
                                            .number()
                                            .min(1)
                                            .max(dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneLimitMax)
                                            .default(
                                                dashboardsPartialUpdateBodyTilesItemWidgetOneConfigOneOneoneLimitDefault
                                            )
                                            .describe('Maximum number of rows to show.'),
                                    }),
                                ])
                                .optional()
                                .describe("Widget-specific configuration. Shape depends on the tile's widget_type."),
                            name: zod
                                .string()
                                .max(dashboardsPartialUpdateBodyTilesItemWidgetOneNameMax)
                                .nullish()
                                .describe('Optional custom display name for the widget tile.'),
                            description: zod
                                .string()
                                .optional()
                                .describe('Optional markdown description shown when show_description is enabled.'),
                        })
                        .optional()
                        .describe('Nested widget row updates.'),
                })
            )
            .optional()
            .describe(
                'Dashboard tiles to update, each identified by its tile id. Any tile type accepts `layouts` to set its grid position and size. Widget tiles also accept nested widget.config patches.'
            ),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsPartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe(
        'OpenAPI-only PATCH body for dashboards (agents\/MCP).\n\nMust be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``\nreplaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.'
    )

/**
 * Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile).
 */
export const DashboardsCopyTileCreateBody = /* @__PURE__ */ zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

/**
 * Add a markdown text tile to a dashboard.
 *
 * Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
 * or annotations between insight tiles to give the dashboard structure.
 */
export const dashboardsCreateTextTileCreateBodyTypeDefault = `text`
export const dashboardsCreateTextTileCreateBodyBodyMax = 4000

export const dashboardsCreateTextTileCreateBodyAgentContextMax = 10000

export const dashboardsCreateTextTileCreateBodyColorMax = 400

export const DashboardsCreateTextTileCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['text', 'image'])
        .describe('\* `text` - text\n\* `image` - image')
        .default(dashboardsCreateTextTileCreateBodyTypeDefault)
        .describe(
            'Tile type. Use image for a body with exactly one Markdown image. Defaults to text.\n\n\* `text` - text\n\* `image` - image'
        ),
    body: zod
        .string()
        .min(1)
        .max(dashboardsCreateTextTileCreateBodyBodyMax)
        .describe(
            'Markdown body for the dashboard tile. Text tiles support headings, lists, and inline formatting. Image tiles require exactly one Markdown image. Max 4000 characters.'
        ),
    agent_context: zod
        .string()
        .max(dashboardsCreateTextTileCreateBodyAgentContextMax)
        .nullish()
        .describe(
            "Optional context that helps AI agents make consistent dashboard updates, such as Data Catalog metric names, data sources, tile-specific query assumptions, caveats, or editing guidance. PostHog's Data Catalog is the semantic layer. Store canonical metric definitions there, not in this field. An empty string or null means there is no agent context. Shared and exported dashboards, and organizations without AI data processing approval, omit this field. Max 10000 characters."
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
 *
 * Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
 * object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
 * use the dashboard delete endpoint instead.
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
        .enum(['preserve', 'two_column', 'three_column', 'full_width'])
        .describe(
            '\* `preserve` - preserve\n\* `two_column` - two_column\n\* `three_column` - three_column\n\* `full_width` - full_width'
        )
        .default(dashboardsReorderTilesCreateBodyLayoutDefault)
        .describe(
            "How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height and only repacks positions in the new order. Use the other modes only when every tile should use the same size: 'two_column' makes every tile 6-wide × 5-tall, 'three_column' makes every tile 4-wide × 5-tall, and 'full_width' makes every tile 12-wide × 5-tall.\n\n\* `preserve` - preserve\n\* `two_column` - two_column\n\* `three_column` - three_column\n\* `full_width` - full_width"
        ),
})

/**
 * Update the markdown body, layout, or color of an existing text tile on a dashboard.
 */
export const dashboardsUpdateTextTileCreateBodyBodyMax = 4000

export const dashboardsUpdateTextTileCreateBodyAgentContextMax = 10000

export const dashboardsUpdateTextTileCreateBodyColorMax = 400

export const DashboardsUpdateTextTileCreateBody = /* @__PURE__ */ zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to update. Use dashboard-get to look up tile IDs.'),
    body: zod
        .string()
        .min(1)
        .max(dashboardsUpdateTextTileCreateBodyBodyMax)
        .optional()
        .describe('New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.'),
    agent_context: zod
        .string()
        .max(dashboardsUpdateTextTileCreateBodyAgentContextMax)
        .nullish()
        .describe(
            "Optional context that helps AI agents make consistent dashboard updates, such as Data Catalog metric names, data sources, tile-specific query assumptions, caveats, or editing guidance. PostHog's Data Catalog is the semantic layer. Store canonical metric definitions there, not in this field. An empty string or null means there is no agent context. Shared and exported dashboards, and organizations without AI data processing approval, omit this field. Max 10000 characters."
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
export const dashboardsWidgetsBatchCreateBodyWidgetsItemNameMax = 400

export const dashboardsWidgetsBatchCreateBodyWidgetsMax = 10

export const DashboardsWidgetsBatchCreateBody = /* @__PURE__ */ zod
    .object({
        widgets: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(dashboardsWidgetsBatchCreateBodyWidgetsItemNameMax)
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
                                .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
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
                                .describe(
                                    'Layout for the small (mobile) breakpoint, on a 1-column grid. The dashboard derives this layout from the sm order and heights, so a stored xs box does not change what renders.'
                                ),
                        })
                        .optional()
                        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
                    show_description: zod
                        .boolean()
                        .optional()
                        .describe('Whether to show the description on the dashboard tile.'),
                    widget_type: zod
                        .enum([
                            'activity_events_list',
                            'canvas_app',
                            'conversations_recent_tickets',
                            'error_tracking_list',
                            'experiment_results',
                            'experiments_list',
                            'logs_list',
                            'metrics_table',
                            'notebook_widget',
                            'session_replay_list',
                            'survey_results',
                        ])
                        .describe(
                            '\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `metrics_table` - Metrics Table\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                        )
                        .describe(
                            'Widget type to add. Use dashboard-widget-catalog-list to pick one.\n\n\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `metrics_table` - Metrics Table\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                        ),
                    config: zod
                        .record(zod.string(), zod.unknown())
                        .describe(
                            "Widget configuration as a JSON object. Its keys depend on widget_type: read that type's config_schema from dashboard-widget-catalog-list. The API validates the config and returns a 400 that names each invalid field."
                        ),
                })
            )
            .min(1)
            .max(dashboardsWidgetsBatchCreateBodyWidgetsMax)
            .describe(
                'Widget tiles to add atomically. Supported widget_type values: activity_events_list, canvas_app, conversations_recent_tickets, error_tracking_list, experiment_results, experiments_list, logs_list, metrics_table, notebook_widget, session_replay_list, survey_results. Use dashboard-widget-catalog-list for per-type config_schema documentation. (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.')

/**
 * Update the settings of existing widgets in place, atomically — config, name, and description.
 *
 * Each entry targets a widget by its tile_id and reuses the same write path as the dashboard PATCH endpoint.
 * The widget_type is immutable. This edits widget settings only (config, name, description); tile placement
 * (layouts, show_description) is a dashboard concern — use the dashboard PATCH endpoint or reorder_tiles for
 * that. All updates succeed or fail together. To add new widgets, use the widgets/batch POST endpoint; to
 * remove one, use delete_tile.
 */
export const dashboardsUpdateWidgetsBatchBodyWidgetsItemNameMax = 400

export const dashboardsUpdateWidgetsBatchBodyWidgetsMax = 10

export const DashboardsUpdateWidgetsBatchBody = /* @__PURE__ */ zod
    .object({
        widgets: zod
            .array(
                zod.object({
                    tile_id: zod
                        .number()
                        .describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
                    name: zod
                        .string()
                        .max(dashboardsUpdateWidgetsBatchBodyWidgetsItemNameMax)
                        .nullish()
                        .describe(
                            'New display name for the widget. Empty string or null clears it; omit to leave unchanged.'
                        ),
                    description: zod
                        .string()
                        .optional()
                        .describe('New markdown description for the widget. Omit to leave unchanged.'),
                    widget_type: zod
                        .enum([
                            'activity_events_list',
                            'canvas_app',
                            'conversations_recent_tickets',
                            'error_tracking_list',
                            'experiment_results',
                            'experiments_list',
                            'logs_list',
                            'metrics_table',
                            'notebook_widget',
                            'session_replay_list',
                            'survey_results',
                        ])
                        .describe(
                            '\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `metrics_table` - Metrics Table\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results'
                        )
                        .optional()
                        .describe(
                            "The tile's widget type. It cannot be changed, so omit it or pass the current type.\n\n\* `activity_events_list` - Activity Events List\n\* `canvas_app` - Canvas App\n\* `conversations_recent_tickets` - Conversations Recent Tickets\n\* `error_tracking_list` - Error Tracking List\n\* `experiment_results` - Experiment Results\n\* `experiments_list` - Experiments List\n\* `logs_list` - Logs List\n\* `metrics_table` - Metrics Table\n\* `notebook_widget` - Notebook Widget\n\* `session_replay_list` - Session Replay List\n\* `survey_results` - Survey Results"
                        ),
                    config: zod
                        .record(zod.string(), zod.unknown())
                        .optional()
                        .describe(
                            "Widget configuration as a JSON object. Its keys depend on widget_type: read that type's config_schema from dashboard-widget-catalog-list. The API validates the config and returns a 400 that names each invalid field. Each top-level key you send replaces the stored value, and keys you leave out stay as they are. Omit config to leave it unchanged."
                        ),
                })
            )
            .min(1)
            .max(dashboardsUpdateWidgetsBatchBodyWidgetsMax)
            .optional()
            .describe(
                'Widget tiles to update atomically, each identified by its tile_id. config shape is per widget_type; see dashboard-widget-catalog-list for per-type config_schema (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-update schema with widget_type-discriminated config shapes for agents.')

/**
 * Soft-delete up to 100 dashboards. Optionally delete insights with no remaining dashboard. Report missing or inaccessible dashboards as skipped.
 */

export const dashboardsBulkDeleteCreateBodyIdsMax = 100

export const dashboardsBulkDeleteCreateBodyDeleteInsightsDefault = false

export const DashboardsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number().min(1))
        .max(dashboardsBulkDeleteCreateBodyIdsMax)
        .describe('Dashboard IDs to soft-delete. At most 100 IDs per request.'),
    delete_insights: zod
        .boolean()
        .default(dashboardsBulkDeleteCreateBodyDeleteInsightsDefault)
        .describe('Also delete insights that have no remaining dashboard after deletion. Defaults to false.'),
})

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
export const dashboardsBulkUpdateTagsCreateBodyIdsMax = 500

export const dashboardsBulkUpdateTagsCreateBodyTagsItemMax = 255

export const dashboardsBulkUpdateTagsCreateBodyTagsMax = 100

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
    tags: zod
        .array(zod.string().max(dashboardsBulkUpdateTagsCreateBodyTagsItemMax))
        .max(dashboardsBulkUpdateTagsCreateBodyTagsMax)
        .describe('Tag names to add, remove, or set (up to 100 per request, 255 characters each).'),
})

export const dashboardsCreateFromTemplateJsonCreateBodyNameMax = 400

export const dashboardsCreateFromTemplateJsonCreateBodyBreakdownColorsItemColorTokenRegExp = new RegExp(
    '^preset-[1-9][0-9]\*$'
)
export const dashboardsCreateFromTemplateJsonCreateBodyGroupsTitleMax = 200

export const dashboardsCreateFromTemplateJsonCreateBodyGroupTitlesMaxOne = 200

export const dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateFromTemplateJsonCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateFromTemplateJsonCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsCreateFromTemplateJsonCreateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        groups: zod
            .record(
                zod.string(),
                zod.object({
                    title: zod
                        .string()
                        .max(dashboardsCreateFromTemplateJsonCreateBodyGroupsTitleMax)
                        .optional()
                        .describe(
                            'Heading for the group. When it is blank or omitted, the heading shows the number of tiles.'
                        ),
                    collapsed: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether the group starts closed. Defaults to false. When a viewer opens or closes the group, their browser keeps that choice and it wins over this default. A closed group loads its tiles when a viewer opens it.'
                        ),
                    color: zod
                        .union([
                            zod
                                .enum(['blue', 'purple', 'green', 'yellow', 'orange', 'red'])
                                .describe(
                                    '\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Color of a dot before the group heading. Null or omitted shows no dot.\n\n\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                        ),
                })
            )
            .nullish()
            .describe(
                "Settings for tile groups, keyed by the tiles' group_key. Each group shows as a band of its tiles under a heading that viewers can open and close. Viewers who do not have bands yet see only the group title above its tiles. A write replaces the whole map. Send an empty object or null to remove all group settings."
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsCreateFromTemplateJsonCreateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                'Deprecated: use groups. Titles for tile groups, keyed by group_key. A write replaces all titles and keeps the other group settings. Send an empty object or null to clear titles. Do not send it with groups.'
            ),
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
 * Enforces uniqueness (one per tag per team).
 * Returns 409 if unlisted dashboard with this tag already exists.
 */
export const dashboardsCreateUnlistedDashboardCreateBodyNameMax = 400

export const dashboardsCreateUnlistedDashboardCreateBodyBreakdownColorsItemColorTokenRegExp = new RegExp(
    '^preset-[1-9][0-9]\*$'
)
export const dashboardsCreateUnlistedDashboardCreateBodyGroupsTitleMax = 200

export const dashboardsCreateUnlistedDashboardCreateBodyGroupTitlesMaxOne = 200

export const dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateUnlistedDashboardCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateUnlistedDashboardCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod
            .array(
                zod.object({
                    breakdownValue: zod
                        .string()
                        .describe('The breakdown value this color applies to, as it appears in the chart legend.'),
                    colorToken: zod
                        .string()
                        .regex(dashboardsCreateUnlistedDashboardCreateBodyBreakdownColorsItemColorTokenRegExp)
                        .nullable()
                        .describe(
                            'Palette slot to color the value with, as `preset-1` upwards. Not a CSS color: a hex value is rejected. Null leaves the value on its default color.'
                        ),
                    breakdownType: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown type the value came from, such as `event`, `person`, `session`, or `cohort`.'
                        ),
                    breakdownProperty: zod
                        .string()
                        .nullish()
                        .describe(
                            'Breakdown property the color is scoped to, so the color applies only to tiles that break down by that property. Omit to apply it under every property.'
                        ),
                    source: zod
                        .union([
                            zod.enum(['auto', 'manual']).describe('\* `auto` - auto\n\* `manual` - manual'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            '`manual` for a color a person picked, `auto` for one the dashboard assigned.\n\n\* `auto` - auto\n\* `manual` - manual'
                        ),
                })
            )
            .nullish()
            .describe(
                "Colors pinned to specific breakdown values across the dashboard's tiles. A list of entries, not an object keyed by breakdown value. Send an empty list to clear them."
            ),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        grid_spacing: zod
            .enum(['tight', 'condensed', 'standard', 'relaxed', 'wide'])
            .describe(
                '\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            )
            .optional()
            .describe(
                'Named tile density preset. Use tight, condensed, standard, relaxed, or wide.\n\n\* `tight` - tight\n\* `condensed` - condensed\n\* `standard` - standard\n\* `relaxed` - relaxed\n\* `wide` - wide'
            ),
        layout_compaction: zod
            .enum(['vertical', 'horizontal', 'stable'])
            .describe('\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable')
            .optional()
            .describe(
                'How tiles rearrange after a move or resize. vertical stacks tiles upward, horizontal stacks tiles to the left, and stable preserves positions while moving colliding tiles.\n\n\* `vertical` - vertical\n\* `horizontal` - horizontal\n\* `stable` - stable'
            ),
        groups: zod
            .record(
                zod.string(),
                zod.object({
                    title: zod
                        .string()
                        .max(dashboardsCreateUnlistedDashboardCreateBodyGroupsTitleMax)
                        .optional()
                        .describe(
                            'Heading for the group. When it is blank or omitted, the heading shows the number of tiles.'
                        ),
                    collapsed: zod
                        .boolean()
                        .optional()
                        .describe(
                            'Whether the group starts closed. Defaults to false. When a viewer opens or closes the group, their browser keeps that choice and it wins over this default. A closed group loads its tiles when a viewer opens it.'
                        ),
                    color: zod
                        .union([
                            zod
                                .enum(['blue', 'purple', 'green', 'yellow', 'orange', 'red'])
                                .describe(
                                    '\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Color of a dot before the group heading. Null or omitted shows no dot.\n\n\* `blue` - Blue\n\* `purple` - Purple\n\* `green` - Green\n\* `yellow` - Yellow\n\* `orange` - Orange\n\* `red` - Red'
                        ),
                })
            )
            .nullish()
            .describe(
                "Settings for tile groups, keyed by the tiles' group_key. Each group shows as a band of its tiles under a heading that viewers can open and close. Viewers who do not have bands yet see only the group title above its tiles. A write replaces the whole map. Send an empty object or null to remove all group settings."
            ),
        group_titles: zod
            .record(zod.string(), zod.string().max(dashboardsCreateUnlistedDashboardCreateBodyGroupTitlesMaxOne))
            .nullish()
            .describe(
                'Deprecated: use groups. Titles for tile groups, keyed by group_key. A write replaces all titles and keeps the other group settings. Send an empty object or null to clear titles. Do not send it with groups.'
            ),
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
