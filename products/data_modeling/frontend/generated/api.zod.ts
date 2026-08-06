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

export const dataModelingDagsPartialUpdateBodyNameMax = 2048

export const DataModelingDagsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataModelingDagsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name for this DAG'),
    description: zod.string().optional().describe("Optional description of the DAG's purpose"),
    sync_frequency: zod.string().nullish().describe("Sync frequency string (e.g. '24hour', '7day')"),
})

export const DataModelingEdgesCreateBody = /* @__PURE__ */ zod.object({
    dag: zod.uuid(),
    properties: zod.unknown().optional(),
})

export const DataModelingEdgesUpdateBody = /* @__PURE__ */ zod.object({
    dag: zod.uuid(),
    properties: zod.unknown().optional(),
})

export const DataModelingEdgesPartialUpdateBody = /* @__PURE__ */ zod.object({
    dag: zod.uuid().optional(),
    properties: zod.unknown().optional(),
})

export const dataModelingNodesCreateBodyNameMax = 2048

export const dataModelingNodesCreateBodyDescriptionMax = 1024

export const DataModelingNodesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesCreateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint'),
    dag: zod.uuid(),
    description: zod.string().max(dataModelingNodesCreateBodyDescriptionMax).optional(),
})

export const dataModelingNodesUpdateBodyNameMax = 2048

export const dataModelingNodesUpdateBodyDescriptionMax = 1024

export const DataModelingNodesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesUpdateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint'),
    dag: zod.uuid(),
    description: zod.string().max(dataModelingNodesUpdateBodyDescriptionMax).optional(),
})

export const dataModelingNodesPartialUpdateBodyNameMax = 2048

export const dataModelingNodesPartialUpdateBodyDescriptionMax = 1024

export const DataModelingNodesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesPartialUpdateBodyNameMax).optional(),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint'),
    dag: zod.uuid().optional(),
    description: zod.string().max(dataModelingNodesPartialUpdateBodyDescriptionMax).optional(),
})

/**
 * Materialize just this single node.
 */
export const dataModelingNodesMaterializeCreateBodyNameMax = 2048

export const dataModelingNodesMaterializeCreateBodyDescriptionMax = 1024

export const DataModelingNodesMaterializeCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesMaterializeCreateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint'),
    dag: zod.uuid(),
    description: zod.string().max(dataModelingNodesMaterializeCreateBodyDescriptionMax).optional(),
})

/**
 * Run this node and its upstream or downstream dependencies.
 *
 * Request body:
 *     direction: "upstream" | "downstream" (required)
 *         - "upstream": Run all ancestors of this node, plus this node
 *         - "downstream": Run this node and all its descendants
 */
export const dataModelingNodesRunCreateBodyNameMax = 2048

export const dataModelingNodesRunCreateBodyDescriptionMax = 1024

export const DataModelingNodesRunCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesRunCreateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint'),
    dag: zod.uuid(),
    description: zod.string().max(dataModelingNodesRunCreateBodyDescriptionMax).optional(),
})
