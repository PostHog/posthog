/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    CertificationCreateApi,
    DataCatalogMetricApi,
    DataCatalogMetricRunRequestApi,
    DataCatalogRelationshipProposalApi,
    PatchedDataCatalogMetricApi,
    RelationshipRejectApi,
} from './api.zod.schemas'

/**
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const DataCatalogCertificationsCreateBody = CertificationCreateApi

/**
 * Create a metric, or refine the one already holding this name for the team.
 */
export const DataCatalogMetricsCreateBody = DataCatalogMetricApi

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const DataCatalogMetricsUpdateBody = DataCatalogMetricApi

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const DataCatalogMetricsPartialUpdateBody = PatchedDataCatalogMetricApi

/**
 * Execute the metric's definition and return the normalized result envelope.
 */
export const DataCatalogMetricsRunCreateBody = DataCatalogMetricRunRequestApi

/**
 * Reviewed join facts. Accepting one promotes it to a real DataWarehouseJoin; rejections persist.
 */
export const DataCatalogRelationshipProposalsCreateBody = DataCatalogRelationshipProposalApi

/**
 * Reject the proposal. Persists forever so the pair is never re-proposed.
 */
export const DataCatalogRelationshipProposalsRejectCreateBody = RelationshipRejectApi
