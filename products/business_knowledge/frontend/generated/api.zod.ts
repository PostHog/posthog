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
    CreateTextSourceApi,
    GapActionApi,
    GapTopicActionApi,
    KnowledgeSourceApi,
    PatchedUpdateTextSourceApi,
} from './api.zod.schemas'

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const BusinessKnowledgeGapSuggestionsAcceptCreateBody = GapActionApi

/**
 * Accept all pending suggestions for a normalized topic cluster.
 */
export const BusinessKnowledgeGapSuggestionsAcceptTopicCreateBody = GapTopicActionApi

/**
 * Dismiss all pending suggestions for a normalized topic cluster.
 */
export const BusinessKnowledgeGapSuggestionsDismissTopicCreateBody = GapTopicActionApi

export const BusinessKnowledgeSourcesCreateBody = CreateTextSourceApi

export const BusinessKnowledgeSourcesPartialUpdateBody = PatchedUpdateTextSourceApi

export const BusinessKnowledgeSourcesRefreshCreateBody = KnowledgeSourceApi
