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

export const KnowledgeDocumentWindowApi = zod
    .object({
        chunk_id: zod.uuid().describe('Stable identifier of this chunk. Same value used in search results.'),
        ordinal: zod
            .number()
            .describe(
                'Zero-based position of this chunk within its document. Use it as `around_ordinal` to recenter the window.'
            ),
        content: zod.string().describe("The chunk's text content."),
        heading_path: zod
            .string()
            .describe(
                'Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure.'
            ),
        source_name: zod.string().describe('Human label of the knowledge source this chunk belongs to.'),
        document_title: zod.string().describe('Title of the document this chunk belongs to.'),
    })
    .describe(
        'One chunk in a drill-down window over a single knowledge document.\n\nOutput-only — the rows come from the `get_document_window` logic helper\n(a `KnowledgeSearchResult` dataclass), not the ORM, so this is a plain\nread serializer rather than a `ModelSerializer`.'
    )

export type KnowledgeDocumentWindowApi = zod.input<typeof KnowledgeDocumentWindowApi>
export type KnowledgeDocumentWindowApiOutput = zod.output<typeof KnowledgeDocumentWindowApi>

export const KnowledgeSearchResultApi = zod
    .object({
        chunk_id: zod.uuid().describe('Stable identifier of this chunk.'),
        document_id: zod
            .uuid()
            .describe(
                'ID of the parent document. Pass to the document-window endpoint with `around_ordinal` to drill down.'
            ),
        ordinal: zod
            .number()
            .describe(
                'Zero-based position of this chunk within its document. Use as `around_ordinal` in the document-window endpoint.'
            ),
        source_id: zod.uuid().describe('ID of the knowledge source this chunk belongs to.'),
        source_name: zod.string().describe('Human label of the knowledge source this chunk belongs to.'),
        source_type: zod.string().describe('Source type (text, url, or file).'),
        document_title: zod.string().describe('Title of the document this chunk belongs to.'),
        heading_path: zod
            .string()
            .describe(
                'Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure.'
            ),
        content: zod.string().describe("The chunk's text content."),
    })
    .describe(
        'One ranked chunk from a business knowledge search.\n\nOutput-only — the rows come from the ``search_knowledge_for_team`` logic\nhelper (a ``KnowledgeSearchResult`` dataclass), not the ORM.'
    )

export type KnowledgeSearchResultApi = zod.input<typeof KnowledgeSearchResultApi>
export type KnowledgeSearchResultApiOutput = zod.output<typeof KnowledgeSearchResultApi>

export const KnowledgeGapSuggestionApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this gap suggestion.'),
    ticket_id: zod.uuid().describe('The ticket that surfaced this gap.'),
    topic: zod.string().describe("Raw topic the AI couldn't answer."),
    normalized_topic: zod.string().describe('Normalized cluster key for grouping.'),
    ticket_type: zod.string().describe('Ticket classification type.'),
    outcome: zod.string().describe('Pipeline outcome that produced this gap.'),
    status: zod.string().describe('Current status: pending, accepted, or dismissed.'),
    resolved_source_id: zod.uuid().nullable().describe('Knowledge source created to fill this gap.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this gap was first recorded.'),
})

export type KnowledgeGapSuggestionApi = zod.input<typeof KnowledgeGapSuggestionApi>
export type KnowledgeGapSuggestionApiOutput = zod.output<typeof KnowledgeGapSuggestionApi>

export const PaginatedKnowledgeGapSuggestionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(KnowledgeGapSuggestionApi),
})

export type PaginatedKnowledgeGapSuggestionListApi = zod.input<typeof PaginatedKnowledgeGapSuggestionListApi>
export type PaginatedKnowledgeGapSuggestionListApiOutput = zod.output<typeof PaginatedKnowledgeGapSuggestionListApi>

export const GapActionApi = zod.object({
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

export type GapActionApi = zod.input<typeof GapActionApi>
export type GapActionApiOutput = zod.output<typeof GapActionApi>

export const GapTopicActionApi = zod.object({
    normalized_topic: zod.string().describe('The normalized topic key identifying the gap cluster to act on.'),
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

export type GapTopicActionApi = zod.input<typeof GapTopicActionApi>
export type GapTopicActionApiOutput = zod.output<typeof GapTopicActionApi>

export const GapTopicActionResultApi = zod.object({
    normalized_topic: zod.string().describe('The normalized topic cluster that was acted on.'),
    updated: zod.number().describe('Number of gap rows whose status changed.'),
})

export type GapTopicActionResultApi = zod.input<typeof GapTopicActionResultApi>
export type GapTopicActionResultApiOutput = zod.output<typeof GapTopicActionResultApi>

export const KnowledgeSourceSourceTypeEnumApi = zod
    .enum(['text', 'url', 'file'])
    .describe('\* `text` - Text\n\* `url` - URL\n\* `file` - File')

export type KnowledgeSourceSourceTypeEnumApi = zod.input<typeof KnowledgeSourceSourceTypeEnumApi>
export type KnowledgeSourceSourceTypeEnumApiOutput = zod.output<typeof KnowledgeSourceSourceTypeEnumApi>

export const KnowledgeSourceStatusEnumApi = zod
    .enum(['pending', 'processing', 'ready', 'error'])
    .describe('\* `pending` - Pending\n\* `processing` - Processing\n\* `ready` - Ready\n\* `error` - Error')

export type KnowledgeSourceStatusEnumApi = zod.input<typeof KnowledgeSourceStatusEnumApi>
export type KnowledgeSourceStatusEnumApiOutput = zod.output<typeof KnowledgeSourceStatusEnumApi>

export const LastRefreshStatusEnumApi = zod
    .enum(['success', 'not_modified', 'error'])
    .describe('\* `success` - Success\n\* `not_modified` - Not modified\n\* `error` - Error')

export type LastRefreshStatusEnumApi = zod.input<typeof LastRefreshStatusEnumApi>
export type LastRefreshStatusEnumApiOutput = zod.output<typeof LastRefreshStatusEnumApi>

export const RefreshIntervalEnumApi = zod
    .enum(['manual', '1h', '6h', '24h', '7d'])
    .describe(
        '\* `manual` - Manual only\n\* `1h` - Every hour\n\* `6h` - Every 6 hours\n\* `24h` - Every day\n\* `7d` - Every week'
    )

export type RefreshIntervalEnumApi = zod.input<typeof RefreshIntervalEnumApi>
export type RefreshIntervalEnumApiOutput = zod.output<typeof RefreshIntervalEnumApi>

export const EmbeddingStatusEnumApi = zod.enum(['pending', 'completed', 'disabled'])

export type EmbeddingStatusEnumApi = zod.input<typeof EmbeddingStatusEnumApi>
export type EmbeddingStatusEnumApiOutput = zod.output<typeof EmbeddingStatusEnumApi>

export const CrawlModeEnumApi = zod
    .enum(['single', 'sitemap', 'same_origin', 'github_repo'])
    .describe(
        '\* `single` - Single page\n\* `sitemap` - Sitemap\n\* `same_origin` - Same origin crawl\n\* `github_repo` - GitHub repository'
    )

export type CrawlModeEnumApi = zod.input<typeof CrawlModeEnumApi>
export type CrawlModeEnumApiOutput = zod.output<typeof CrawlModeEnumApi>

export const knowledgeSourceApiDocumentCountDefault = 0
export const knowledgeSourceApiChunkCountDefault = 0

export const KnowledgeSourceApi = zod.object({
    id: zod.uuid(),
    team_id: zod.number(),
    name: zod.string(),
    source_type: KnowledgeSourceSourceTypeEnumApi,
    status: KnowledgeSourceStatusEnumApi,
    error_message: zod.string(),
    document_count: zod
        .number()
        .default(knowledgeSourceApiDocumentCountDefault)
        .describe('Number of documents belonging to this source.'),
    chunk_count: zod
        .number()
        .default(knowledgeSourceApiChunkCountDefault)
        .describe('Number of chunks belonging to this source.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    source_url: zod.url(),
    last_refresh_at: zod.iso.datetime({ offset: true }).nullable(),
    last_refresh_status: LastRefreshStatusEnumApi,
    last_refresh_error: zod.string(),
    refresh_interval: RefreshIntervalEnumApi,
    next_refresh_at: zod
        .string()
        .nullable()
        .describe(
            'When the background coordinator will next auto-refresh this source. Null for manual sources or sources never refreshed.'
        ),
    has_unsafe_documents: zod
        .boolean()
        .describe(
            'True when at least one document in this source was flagged unsafe by the content classifier and is therefore excluded from agent search.'
        ),
    embedding_status: EmbeddingStatusEnumApi.describe(
        'Semantic-index state of this source. A `ready` source serves keyword (full-text) search immediately, but semantic search needs a background job to classify and embed its documents, which can take up to an hour. `pending` — at least one document is still awaiting classification or embedding. `completed` — every eligible document has been submitted to the embedding pipeline. `disabled` — the organization has not approved AI data processing, so embeddings never run and search stays keyword-only. Only meaningful while `status` is `ready`.'
    ),
    crawl_mode: CrawlModeEnumApi,
    crawl_config: zod.unknown(),
    original_filename: zod.string(),
    file_content_type: zod.string(),
    file_size_bytes: zod.number().nullable(),
    always_include: zod.boolean(),
})

export type KnowledgeSourceApi = zod.input<typeof KnowledgeSourceApi>
export type KnowledgeSourceApiOutput = zod.output<typeof KnowledgeSourceApi>

export const PaginatedKnowledgeSourceListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(KnowledgeSourceApi),
})

export type PaginatedKnowledgeSourceListApi = zod.input<typeof PaginatedKnowledgeSourceListApi>
export type PaginatedKnowledgeSourceListApiOutput = zod.output<typeof PaginatedKnowledgeSourceListApi>

export const createTextSourceApiNameMax = 255

export const createTextSourceApiAlwaysIncludeDefault = false

export const CreateTextSourceApi = zod.object({
    name: zod
        .string()
        .max(createTextSourceApiNameMax)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    text: zod
        .string()
        .describe(
            'Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL\/file support in Stage 2\/3.'
        ),
    always_include: zod
        .boolean()
        .default(createTextSourceApiAlwaysIncludeDefault)
        .describe(
            "When true, this source's content is injected into every support reply prompt as general context (tone, policies, direction)."
        ),
})

export type CreateTextSourceApi = zod.input<typeof CreateTextSourceApi>
export type CreateTextSourceApiOutput = zod.output<typeof CreateTextSourceApi>

export const patchedUpdateTextSourceApiNameMax = 255

export const PatchedUpdateTextSourceApi = zod
    .object({
        name: zod
            .string()
            .max(patchedUpdateTextSourceApiNameMax)
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

export type PatchedUpdateTextSourceApi = zod.input<typeof PatchedUpdateTextSourceApi>
export type PatchedUpdateTextSourceApiOutput = zod.output<typeof PatchedUpdateTextSourceApi>
