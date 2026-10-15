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
})

/**
 * Materialize just this single node.
 */
export const dataModelingNodesMaterializeCreateBodyNameMax = 2048

export const dataModelingNodesMaterializeCreateBodyDescriptionMax = 1024

export const DataModelingNodesMaterializeCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingNodesMaterializeCreateBodyNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint', 'metric'])
        .optional()
        .describe(
            '\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint\n\* `metric` - Metric'
        ),
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
        .enum(['table', 'view', 'matview', 'endpoint', 'metric'])
        .optional()
        .describe(
            '\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint\n\* `metric` - Metric'
        ),
    description: zod.string().max(dataModelingNodesRunCreateBodyDescriptionMax).optional(),
})
