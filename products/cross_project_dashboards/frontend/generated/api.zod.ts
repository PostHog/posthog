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
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsCreateBodyNameMax = 400

export const CrossProjectDashboardsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(crossProjectDashboardsCreateBodyNameMax)
            .describe('Name shown in the dashboard list and page header.'),
        description: zod.string().optional().describe('Optional longer description.'),
        filters: zod
            .unknown()
            .optional()
            .describe(
                'Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected.'
            ),
    })
    .describe(
        "Carries tile references only.\n\nThe response holds no insight names, queries or results. Each reader fetches each tile from\nthat tile's own project endpoint, so their access, quota and cache key stay correct there."
    )

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesCreateBodyProjectIdMin = -2147483648
export const crossProjectDashboardsTilesCreateBodyProjectIdMax = 2147483647

export const crossProjectDashboardsTilesCreateBodyInsightIdMin = -2147483648
export const crossProjectDashboardsTilesCreateBodyInsightIdMax = 2147483647

export const crossProjectDashboardsTilesCreateBodyColorMax = 400

export const CrossProjectDashboardsTilesCreateBody = /* @__PURE__ */ zod.object({
    project_id: zod
        .number()
        .min(crossProjectDashboardsTilesCreateBodyProjectIdMin)
        .max(crossProjectDashboardsTilesCreateBodyProjectIdMax)
        .describe("Id of the project the tile's insight belongs to."),
    insight_id: zod
        .number()
        .min(crossProjectDashboardsTilesCreateBodyInsightIdMin)
        .max(crossProjectDashboardsTilesCreateBodyInsightIdMax)
        .describe('Id of the insight the tile renders.'),
    layouts: zod.unknown().optional().describe('Grid position and size of the tile, keyed by layout size.'),
    color: zod
        .string()
        .max(crossProjectDashboardsTilesCreateBodyColorMax)
        .nullish()
        .describe('Optional color applied to the tile.'),
    filters_overrides: zod
        .unknown()
        .optional()
        .describe(
            "Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected."
        ),
})

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesUpdateBodyProjectIdMin = -2147483648
export const crossProjectDashboardsTilesUpdateBodyProjectIdMax = 2147483647

export const crossProjectDashboardsTilesUpdateBodyInsightIdMin = -2147483648
export const crossProjectDashboardsTilesUpdateBodyInsightIdMax = 2147483647

export const crossProjectDashboardsTilesUpdateBodyColorMax = 400

export const CrossProjectDashboardsTilesUpdateBody = /* @__PURE__ */ zod.object({
    project_id: zod
        .number()
        .min(crossProjectDashboardsTilesUpdateBodyProjectIdMin)
        .max(crossProjectDashboardsTilesUpdateBodyProjectIdMax)
        .describe("Id of the project the tile's insight belongs to."),
    insight_id: zod
        .number()
        .min(crossProjectDashboardsTilesUpdateBodyInsightIdMin)
        .max(crossProjectDashboardsTilesUpdateBodyInsightIdMax)
        .describe('Id of the insight the tile renders.'),
    layouts: zod.unknown().optional().describe('Grid position and size of the tile, keyed by layout size.'),
    color: zod
        .string()
        .max(crossProjectDashboardsTilesUpdateBodyColorMax)
        .nullish()
        .describe('Optional color applied to the tile.'),
    filters_overrides: zod
        .unknown()
        .optional()
        .describe(
            "Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected."
        ),
})

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesPartialUpdateBodyProjectIdMin = -2147483648
export const crossProjectDashboardsTilesPartialUpdateBodyProjectIdMax = 2147483647

export const crossProjectDashboardsTilesPartialUpdateBodyInsightIdMin = -2147483648
export const crossProjectDashboardsTilesPartialUpdateBodyInsightIdMax = 2147483647

export const crossProjectDashboardsTilesPartialUpdateBodyColorMax = 400

export const CrossProjectDashboardsTilesPartialUpdateBody = /* @__PURE__ */ zod.object({
    project_id: zod
        .number()
        .min(crossProjectDashboardsTilesPartialUpdateBodyProjectIdMin)
        .max(crossProjectDashboardsTilesPartialUpdateBodyProjectIdMax)
        .optional()
        .describe("Id of the project the tile's insight belongs to."),
    insight_id: zod
        .number()
        .min(crossProjectDashboardsTilesPartialUpdateBodyInsightIdMin)
        .max(crossProjectDashboardsTilesPartialUpdateBodyInsightIdMax)
        .optional()
        .describe('Id of the insight the tile renders.'),
    layouts: zod.unknown().optional().describe('Grid position and size of the tile, keyed by layout size.'),
    color: zod
        .string()
        .max(crossProjectDashboardsTilesPartialUpdateBodyColorMax)
        .nullish()
        .describe('Optional color applied to the tile.'),
    filters_overrides: zod
        .unknown()
        .optional()
        .describe(
            "Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected."
        ),
})

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsUpdateBodyNameMax = 400

export const CrossProjectDashboardsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(crossProjectDashboardsUpdateBodyNameMax)
            .describe('Name shown in the dashboard list and page header.'),
        description: zod.string().optional().describe('Optional longer description.'),
        filters: zod
            .unknown()
            .optional()
            .describe(
                'Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected.'
            ),
    })
    .describe(
        "Carries tile references only.\n\nThe response holds no insight names, queries or results. Each reader fetches each tile from\nthat tile's own project endpoint, so their access, quota and cache key stay correct there."
    )

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsPartialUpdateBodyNameMax = 400

export const CrossProjectDashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(crossProjectDashboardsPartialUpdateBodyNameMax)
            .optional()
            .describe('Name shown in the dashboard list and page header.'),
        description: zod.string().optional().describe('Optional longer description.'),
        filters: zod
            .unknown()
            .optional()
            .describe(
                'Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected.'
            ),
    })
    .describe(
        "Carries tile references only.\n\nThe response holds no insight names, queries or results. Each reader fetches each tile from\nthat tile's own project endpoint, so their access, quota and cache key stay correct there."
    )
