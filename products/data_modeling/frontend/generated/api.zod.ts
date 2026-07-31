/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { DagApi, EdgeApi, NodeApi, PatchedDAGApi, PatchedEdgeApi, PatchedNodeApi } from './api.zod.schemas'

export const DataModelingDagsCreateBody = DagApi

export const DataModelingDagsPartialUpdateBody = PatchedDAGApi

export const DataModelingEdgesCreateBody = EdgeApi

export const DataModelingEdgesUpdateBody = EdgeApi

export const DataModelingEdgesPartialUpdateBody = PatchedEdgeApi

export const DataModelingNodesCreateBody = NodeApi

export const DataModelingNodesUpdateBody = NodeApi

export const DataModelingNodesPartialUpdateBody = PatchedNodeApi

/**
 * Materialize just this single node.
 */
export const DataModelingNodesMaterializeCreateBody = NodeApi

/**
 * Run this node and its upstream or downstream dependencies.
 *
 * Request body:
 *     direction: "upstream" | "downstream" (required)
 *         - "upstream": Run all ancestors of this node, plus this node
 *         - "downstream": Run this node and all its descendants
 */
export const DataModelingNodesRunCreateBody = NodeApi
