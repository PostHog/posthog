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

export const dataModelingDagsListResponseResultsItemNameMax = 2048

export const dataModelingDagsListResponseResultsItemNodeCountDefault = 0

export const DataModelingDagsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod
                .string()
                .max(dataModelingDagsListResponseResultsItemNameMax)
                .describe('Human-readable name for this DAG'),
            description: zod.string().optional().describe("Optional description of the DAG's purpose"),
            sync_frequency: zod.string().nullish().describe("Sync frequency string (e.g. '24hour', '7day')"),
            node_count: zod.number(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const dataModelingDagsCreateBodyNameMax = 2048

export const DataModelingDagsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataModelingDagsCreateBodyNameMax).describe('Human-readable name for this DAG'),
    description: zod.string().optional().describe("Optional description of the DAG's purpose"),
    sync_frequency: zod.string().nullish().describe("Sync frequency string (e.g. '24hour', '7day')"),
})

export const DataModelingEdgesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            source_id: zod.uuid(),
            target_id: zod.uuid(),
            dag: zod.uuid(),
            dag_name: zod.string(),
            properties: zod.unknown().optional(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const DataModelingEdgesCreateBody = /* @__PURE__ */ zod.object({
    dag: zod.uuid(),
    properties: zod.unknown().optional(),
})

export const dataModelingNodesListResponseResultsItemNameMax = 2048

export const dataModelingNodesListResponseResultsItemDescriptionMax = 1024

export const DataModelingNodesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(dataModelingNodesListResponseResultsItemNameMax),
            type: zod
                .enum(['table', 'view', 'matview', 'endpoint'])
                .optional()
                .describe('* `table` - Table\n* `view` - View\n* `matview` - Mat View\n* `endpoint` - Endpoint'),
            dag: zod.uuid(),
            dag_name: zod.string(),
            description: zod.string().max(dataModelingNodesListResponseResultsItemDescriptionMax).optional(),
            saved_query_id: zod.uuid().nullable(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            upstream_count: zod.number(),
            downstream_count: zod.number(),
            last_run_at: zod.string().nullable(),
            last_run_status: zod.string().nullable(),
            user_tag: zod.string().nullable(),
            sync_interval: zod.string().nullable(),
        })
    ),
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

/**
 * Get all distinct DAGs for the team.
 */
export const dataModelingNodesDagIdsRetrieveResponseNameMax = 2048

export const dataModelingNodesDagIdsRetrieveResponseDescriptionMax = 1024

export const DataModelingNodesDagIdsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(dataModelingNodesDagIdsRetrieveResponseNameMax),
    type: zod
        .enum(['table', 'view', 'matview', 'endpoint'])
        .optional()
        .describe('* `table` - Table\n* `view` - View\n* `matview` - Mat View\n* `endpoint` - Endpoint'),
    dag: zod.uuid(),
    dag_name: zod.string(),
    description: zod.string().max(dataModelingNodesDagIdsRetrieveResponseDescriptionMax).optional(),
    saved_query_id: zod.uuid().nullable(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    upstream_count: zod.number(),
    downstream_count: zod.number(),
    last_run_at: zod.string().nullable(),
    last_run_status: zod.string().nullable(),
    user_tag: zod.string().nullable(),
    sync_interval: zod.string().nullable(),
})
