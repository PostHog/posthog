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
