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
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const BusinessKnowledgeGapSuggestionsAcceptCreateBody = /* @__PURE__ */ zod.object({
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

/**
 * Accept all pending suggestions for a normalized topic cluster.
 */
export const BusinessKnowledgeGapSuggestionsAcceptTopicCreateBody = /* @__PURE__ */ zod.object({
    normalized_topic: zod.string().describe('The normalized topic key identifying the gap cluster to act on.'),
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

/**
 * Dismiss all pending suggestions for a normalized topic cluster.
 */
export const BusinessKnowledgeGapSuggestionsDismissTopicCreateBody = /* @__PURE__ */ zod.object({
    normalized_topic: zod.string().describe('The normalized topic key identifying the gap cluster to act on.'),
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

export const businessKnowledgeSourcesCreateBodyNameMax = 255

export const businessKnowledgeSourcesCreateBodyAlwaysIncludeDefault = false

export const BusinessKnowledgeSourcesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(businessKnowledgeSourcesCreateBodyNameMax)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    text: zod
        .string()
        .describe(
            'Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL\/file support in Stage 2\/3.'
        ),
    always_include: zod
        .boolean()
        .default(businessKnowledgeSourcesCreateBodyAlwaysIncludeDefault)
        .describe(
            "When true, this source's content is injected into every support reply prompt as general context (tone, policies, direction)."
        ),
})

export const businessKnowledgeSourcesPartialUpdateBodyNameMax = 255

export const BusinessKnowledgeSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(businessKnowledgeSourcesPartialUpdateBodyNameMax)
            .optional()
            .describe('New human label for the source.'),
        text: zod.string().optional().describe('Replacement text. Omit to keep the existing content.'),
        always_include: zod
            .boolean()
            .optional()
            .describe(
                "When true, this source's content is injected into every support reply prompt as general context."
            ),
    })
    .describe(
        'PATCH payload for text sources. All fields optional, at least one\nrequired. `text` triggers a re-chunk; `name` or `always_include` alone does not.'
    )

export const BusinessKnowledgeSourcesRefreshCreateBody = /* @__PURE__ */ zod.looseObject({})
