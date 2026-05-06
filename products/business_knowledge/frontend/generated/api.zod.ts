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

export const BusinessKnowledgeSourcesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(businessKnowledgeSourcesCreateBodyNameMax)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    text: zod
        .string()
        .describe(
            'Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL/file support in Stage 2/3.'
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
    })
    .describe(
        'PATCH payload for text sources. Both fields optional, at least one\nrequired. `text` triggers a re-chunk; `name` alone does not.'
    )

export const BusinessKnowledgeSourcesRefreshCreateBody = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team_id: zod.number(),
    name: zod.string(),
    source_type: zod.string(),
    status: zod.string(),
    error_message: zod.string(),
    document_count: zod.number(),
    chunk_count: zod.number(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    source_url: zod.string().optional(),
    last_refresh_at: zod.iso.datetime({}).nullish(),
    last_refresh_status: zod.string().optional(),
    last_refresh_error: zod.string().optional(),
    crawl_mode: zod.string().optional(),
    crawl_config: zod.record(zod.string(), zod.unknown()).optional(),
    original_filename: zod.string().optional(),
    file_content_type: zod.string().optional(),
    file_size_bytes: zod.number().nullish(),
})
