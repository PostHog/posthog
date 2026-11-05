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

export const DataModelingEdgesUpdateBody = /* @__PURE__ */ zod.object({
    properties: zod.unknown().optional(),
})

export const DataModelingEdgesPartialUpdateBody = /* @__PURE__ */ zod.object({
    properties: zod.unknown().optional(),
})

export const dataModelingNodesUpdateBodyNameMax = 2048

export const dataModelingNodesUpdateBodyDescriptionMax = 1024

export const DataModelingNodesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesUpdateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint', 'metric'])
        .optional()
        .describe(
            '\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint\n\* `metric` - Metric'
        ),
    description: zod.string().max(dataModelingNodesUpdateBodyDescriptionMax).optional(),
    sync_frequency: zod
        .enum(['never', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'])
        .describe(
            '\* `never` - never\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        )
        .optional()
        .describe(
            "How often this view refreshes. 'never' clears the cadence, and with it the pin. Read the stored cadence back from `sync_interval`. Only views and endpoints the team owns accept it.\n\n\* `never` - never\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
        ),
    pinned: zod
        .boolean()
        .optional()
        .describe(
            'Pin this view to its own cadence. A pinned view does not refresh more often when downstream views or endpoints need fresher data, so they read data up to one pinned interval old. Requires a cadence. Set false to refresh as often as downstream views need again.'
        ),
})

export const dataModelingNodesPartialUpdateBodyNameMax = 2048

export const dataModelingNodesPartialUpdateBodyDescriptionMax = 1024

export const DataModelingNodesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesPartialUpdateBodyNameMax).optional(),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint', 'metric'])
        .optional()
        .describe(
            '\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint\n\* `metric` - Metric'
        ),
    description: zod.string().max(dataModelingNodesPartialUpdateBodyDescriptionMax).optional(),
    sync_frequency: zod
        .enum(['never', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'])
        .describe(
            '\* `never` - never\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day'
        )
        .optional()
        .describe(
            "How often this view refreshes. 'never' clears the cadence, and with it the pin. Read the stored cadence back from `sync_interval`. Only views and endpoints the team owns accept it.\n\n\* `never` - never\n\* `15min` - 15min\n\* `30min` - 30min\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day\n\* `30day` - 30day"
        ),
    pinned: zod
        .boolean()
        .optional()
        .describe(
            'Pin this view to its own cadence. A pinned view does not refresh more often when downstream views or endpoints need fresher data, so they read data up to one pinned interval old. Requires a cadence. Set false to refresh as often as downstream views need again.'
        ),
})

/**
 * Run this node with its upstream dependencies or downstream dependents.
 */
export const DataModelingNodesRunCreateBody = /* @__PURE__ */ zod.object({
    direction: zod
        .enum(['upstream', 'downstream'])
        .describe('\* `upstream` - Upstream\n\* `downstream` - Downstream')
        .describe(
            'Run this view with all upstream dependencies or all downstream dependents.\n\n\* `upstream` - Upstream\n\* `downstream` - Downstream'
        ),
})
