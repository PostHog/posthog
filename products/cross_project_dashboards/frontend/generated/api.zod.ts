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

export const crossProjectDashboardsCreateBodyDescriptionDefault = ``
export const crossProjectDashboardsCreateBodyDescriptionMax = 4000

export const CrossProjectDashboardsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(crossProjectDashboardsCreateBodyNameMax)
            .describe('Name shown in the dashboard list and page header.'),
        description: zod
            .string()
            .max(crossProjectDashboardsCreateBodyDescriptionMax)
            .default(crossProjectDashboardsCreateBodyDescriptionDefault)
            .describe('Optional longer description.'),
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
export const crossProjectDashboardsTilesCreateBodyColorMax = 400

export const CrossProjectDashboardsTilesCreateBody = /* @__PURE__ */ zod.object({
    project_id: zod.number().describe("Id of the project the tile's insight belongs to."),
    insight_id: zod.number().describe('Id of the insight the tile renders.'),
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
export const crossProjectDashboardsTilesPartialUpdateBodyColorMax = 400

export const CrossProjectDashboardsTilesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
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
    .describe("A tile's project and insight never change, so an update carries only its placement and styling.")

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsPartialUpdateBodyNameMax = 400

export const crossProjectDashboardsPartialUpdateBodyDescriptionDefault = ``
export const crossProjectDashboardsPartialUpdateBodyDescriptionMax = 4000

export const CrossProjectDashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(crossProjectDashboardsPartialUpdateBodyNameMax)
            .optional()
            .describe('Name shown in the dashboard list and page header.'),
        description: zod
            .string()
            .max(crossProjectDashboardsPartialUpdateBodyDescriptionMax)
            .default(crossProjectDashboardsPartialUpdateBodyDescriptionDefault)
            .describe('Optional longer description.'),
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
