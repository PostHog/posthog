/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const dagApiNameMax = 2048

export const dagApiNodeCountDefault = 0

export const DagApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(dagApiNameMax).describe('Human-readable name for this DAG'),
    description: zod.string().optional().describe("Optional description of the DAG's purpose"),
    sync_frequency: zod.string().nullish().describe("Sync frequency string (e.g. '24hour', '7day')"),
    frequency_managed_by_nodes: zod
        .boolean()
        .describe(
            "True when this team's DAG schedules are driven by per-model freshness targets, so `sync_frequency` no longer controls scheduling and writes to it are rejected. False when the DAG-level frequency still applies."
        ),
    node_count: zod.number().default(dagApiNodeCountDefault),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type DagApi = zod.input<typeof DagApi>
export type DagApiOutput = zod.output<typeof DagApi>

export const PaginatedDAGListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DagApi),
})

export type PaginatedDAGListApi = zod.input<typeof PaginatedDAGListApi>
export type PaginatedDAGListApiOutput = zod.output<typeof PaginatedDAGListApi>

export const patchedDAGApiNameMax = 2048

export const patchedDAGApiNodeCountDefault = 0

export const PatchedDAGApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedDAGApiNameMax).optional().describe('Human-readable name for this DAG'),
    description: zod.string().optional().describe("Optional description of the DAG's purpose"),
    sync_frequency: zod.string().nullish().describe("Sync frequency string (e.g. '24hour', '7day')"),
    frequency_managed_by_nodes: zod
        .boolean()
        .optional()
        .describe(
            "True when this team's DAG schedules are driven by per-model freshness targets, so `sync_frequency` no longer controls scheduling and writes to it are rejected. False when the DAG-level frequency still applies."
        ),
    node_count: zod.number().default(patchedDAGApiNodeCountDefault),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedDAGApi = zod.input<typeof PatchedDAGApi>
export type PatchedDAGApiOutput = zod.output<typeof PatchedDAGApi>

export const EdgeApi = zod.object({
    id: zod.uuid(),
    source_id: zod.uuid(),
    target_id: zod.uuid(),
    dag: zod.uuid(),
    dag_name: zod.string(),
    properties: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type EdgeApi = zod.input<typeof EdgeApi>
export type EdgeApiOutput = zod.output<typeof EdgeApi>

export const PaginatedEdgeListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EdgeApi),
})

export type PaginatedEdgeListApi = zod.input<typeof PaginatedEdgeListApi>
export type PaginatedEdgeListApiOutput = zod.output<typeof PaginatedEdgeListApi>

export const PatchedEdgeApi = zod.object({
    id: zod.uuid().optional(),
    source_id: zod.uuid().optional(),
    target_id: zod.uuid().optional(),
    dag: zod.uuid().optional(),
    dag_name: zod.string().optional(),
    properties: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedEdgeApi = zod.input<typeof PatchedEdgeApi>
export type PatchedEdgeApiOutput = zod.output<typeof PatchedEdgeApi>

export const NodeTypeEnumApi = zod
    .enum(['table', 'view', 'matview', 'endpoint'])
    .describe('\* `table` - Table\n\* `view` - View\n\* `matview` - Mat View\n\* `endpoint` - Endpoint')

export type NodeTypeEnumApi = zod.input<typeof NodeTypeEnumApi>
export type NodeTypeEnumApiOutput = zod.output<typeof NodeTypeEnumApi>

export const NodeSuspensionApi = zod.object({
    at: zod.iso.datetime({ offset: true }).describe('When the node was suspended.'),
    reason: zod.string().describe('Error from the materialization that tripped suspension.'),
    job_id: zod.string().describe('Materialization job that tripped suspension.'),
})

export type NodeSuspensionApi = zod.input<typeof NodeSuspensionApi>
export type NodeSuspensionApiOutput = zod.output<typeof NodeSuspensionApi>

export const nodeApiNameMax = 2048

export const nodeApiDescriptionMax = 1024

export const NodeApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(nodeApiNameMax),
    type: NodeTypeEnumApi.optional(),
    dag: zod.uuid(),
    dag_name: zod.string(),
    description: zod.string().max(nodeApiDescriptionMax).optional(),
    saved_query_id: zod.uuid().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    upstream_count: zod.number(),
    downstream_count: zod.number(),
    last_run_at: zod.string().nullable(),
    last_run_status: zod.string().nullable(),
    user_tag: zod.string().nullable(),
    sync_interval: zod.string().nullable(),
    suspended: zod
        .record(zod.string(), NodeSuspensionApi)
        .describe(
            'Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed.'
        ),
})

export type NodeApi = zod.input<typeof NodeApi>
export type NodeApiOutput = zod.output<typeof NodeApi>

export const PaginatedNodeListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(NodeApi),
})

export type PaginatedNodeListApi = zod.input<typeof PaginatedNodeListApi>
export type PaginatedNodeListApiOutput = zod.output<typeof PaginatedNodeListApi>

export const patchedNodeApiNameMax = 2048

export const patchedNodeApiDescriptionMax = 1024

export const PatchedNodeApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedNodeApiNameMax).optional(),
    type: NodeTypeEnumApi.optional(),
    dag: zod.uuid().optional(),
    dag_name: zod.string().optional(),
    description: zod.string().max(patchedNodeApiDescriptionMax).optional(),
    saved_query_id: zod.uuid().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
    upstream_count: zod.number().optional(),
    downstream_count: zod.number().optional(),
    last_run_at: zod.string().nullish(),
    last_run_status: zod.string().nullish(),
    user_tag: zod.string().nullish(),
    sync_interval: zod.string().nullish(),
    suspended: zod
        .record(zod.string(), NodeSuspensionApi)
        .optional()
        .describe(
            'Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed.'
        ),
})

export type PatchedNodeApi = zod.input<typeof PatchedNodeApi>
export type PatchedNodeApiOutput = zod.output<typeof PatchedNodeApi>

export const NodeResumeApi = zod.object({
    resumed: zod.boolean().describe('False when the node was not suspended to begin with.'),
})

export type NodeResumeApi = zod.input<typeof NodeResumeApi>
export type NodeResumeApiOutput = zod.output<typeof NodeResumeApi>
