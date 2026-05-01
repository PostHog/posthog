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

export const dataModelingDagsCreateBodyNameMax = 2048

export const DataModelingDagsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingDagsCreateBodyNameMax).describe('Human-readable name for this DAG'),
    description: zod.string().optional().describe("Optional description of the DAG's purpose"),
    sync_frequency: zod.string().nullish().describe("Sync frequency string (e.g. '24hour', '7day')"),
})

export const DataModelingEdgesCreateBody = /* @__PURE__ */ zod.object({
    dag: zod.uuid(),
    properties: zod.unknown().optional(),
})

export const dataModelingNodesCreateBodyNameMax = 2048

export const dataModelingNodesCreateBodyDescriptionMax = 1024

export const DataModelingNodesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesCreateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('* `table` - Table\n* `view` - View\n* `matview` - Mat View\n* `endpoint` - Endpoint'),
    dag: zod.uuid(),
    description: zod.string().max(dataModelingNodesCreateBodyDescriptionMax).optional(),
})
