/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * One chunk in a drill-down window over a single knowledge document.
 *
 * Output-only — the rows come from the `get_document_window` logic helper
 * (a `KnowledgeSearchResult` dataclass), not the ORM, so this is a plain
 * read serializer rather than a `ModelSerializer`.
 */
export interface KnowledgeDocumentWindowApi {
    /** Stable identifier of this chunk. Same value used in search results. */
    readonly chunk_id: string
    /** Zero-based position of this chunk within its document. Use it as `around_ordinal` to recenter the window. */
    readonly ordinal: number
    /** The chunk's text content. */
    readonly content: string
    /** Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure. */
    readonly heading_path: string
    /** Human label of the knowledge source this chunk belongs to. */
    readonly source_name: string
    /** Title of the document this chunk belongs to. */
    readonly document_title: string
}

/**
 * One ranked chunk from a business knowledge search.
 *
 * Output-only — the rows come from the ``search_knowledge_for_team`` logic
 * helper (a ``KnowledgeSearchResult`` dataclass), not the ORM.
 */
export interface KnowledgeSearchResultApi {
    /** Stable identifier of this chunk. */
    readonly chunk_id: string
    /** ID of the parent document. Pass to the document-window endpoint with `around_ordinal` to drill down. */
    readonly document_id: string
    /** Zero-based position of this chunk within its document. Use as `around_ordinal` in the document-window endpoint. */
    readonly ordinal: number
    /** ID of the knowledge source this chunk belongs to. */
    readonly source_id: string
    /** Human label of the knowledge source this chunk belongs to. */
    readonly source_name: string
    /** Source type (text, url, or file). */
    readonly source_type: string
    /** Title of the document this chunk belongs to. */
    readonly document_title: string
    /** Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure. */
    readonly heading_path: string
    /** The chunk's text content. */
    readonly content: string
}

export interface KnowledgeGapSuggestionApi {
    /** Unique identifier for this gap suggestion. */
    readonly id: string
    /** The ticket that surfaced this gap. */
    readonly ticket_id: string
    /** Raw topic the AI couldn't answer. */
    readonly topic: string
    /** Normalized cluster key for grouping. */
    readonly normalized_topic: string
    /** Ticket classification type. */
    readonly ticket_type: string
    /** Pipeline outcome that produced this gap. */
    readonly outcome: string
    /** Current status: pending, accepted, or dismissed. */
    readonly status: string
    /**
     * Knowledge source created to fill this gap.
     * @nullable
     */
    readonly resolved_source_id: string | null
    /** When this gap was first recorded. */
    readonly created_at: string
}

export interface PaginatedKnowledgeGapSuggestionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: KnowledgeGapSuggestionApi[]
}

export interface GapActionApi {
    /**
     * Optional knowledge source to link when accepting.
     * @nullable
     */
    resolved_source_id?: string | null
}

export interface GapTopicActionApi {
    /** The normalized topic key identifying the gap cluster to act on. */
    normalized_topic: string
    /**
     * Optional knowledge source to link when accepting.
     * @nullable
     */
    resolved_source_id?: string | null
}

export interface GapTopicActionResultApi {
    /** The normalized topic cluster that was acted on. */
    readonly normalized_topic: string
    /** Number of gap rows whose status changed. */
    readonly updated: number
}

/**
 * * `text` - Text
 * * `url` - URL
 * * `file` - File
 */
export type KnowledgeSourceSourceTypeEnumApi =
    (typeof KnowledgeSourceSourceTypeEnumApi)[keyof typeof KnowledgeSourceSourceTypeEnumApi]

export const KnowledgeSourceSourceTypeEnumApi = {
    Text: 'text',
    Url: 'url',
    File: 'file',
} as const

/**
 * * `pending` - Pending
 * * `processing` - Processing
 * * `ready` - Ready
 * * `error` - Error
 */
export type KnowledgeSourceStatusEnumApi =
    (typeof KnowledgeSourceStatusEnumApi)[keyof typeof KnowledgeSourceStatusEnumApi]

export const KnowledgeSourceStatusEnumApi = {
    Pending: 'pending',
    Processing: 'processing',
    Ready: 'ready',
    Error: 'error',
} as const

/**
 * * `success` - Success
 * * `not_modified` - Not modified
 * * `error` - Error
 */
export type LastRefreshStatusEnumApi = (typeof LastRefreshStatusEnumApi)[keyof typeof LastRefreshStatusEnumApi]

export const LastRefreshStatusEnumApi = {
    Success: 'success',
    NotModified: 'not_modified',
    Error: 'error',
} as const

/**
 * * `manual` - Manual only
 * * `1h` - Every hour
 * * `6h` - Every 6 hours
 * * `24h` - Every day
 * * `7d` - Every week
 */
export type RefreshIntervalEnumApi = (typeof RefreshIntervalEnumApi)[keyof typeof RefreshIntervalEnumApi]

export const RefreshIntervalEnumApi = {
    Manual: 'manual',
    '1h': '1h',
    '6h': '6h',
    '24h': '24h',
    '7d': '7d',
} as const

export type EmbeddingStatusEnumApi = (typeof EmbeddingStatusEnumApi)[keyof typeof EmbeddingStatusEnumApi]

export const EmbeddingStatusEnumApi = {
    Pending: 'pending',
    Completed: 'completed',
    Disabled: 'disabled',
} as const

/**
 * * `single` - Single page
 * * `sitemap` - Sitemap
 * * `same_origin` - Same origin crawl
 * * `github_repo` - GitHub repository
 */
export type CrawlModeEnumApi = (typeof CrawlModeEnumApi)[keyof typeof CrawlModeEnumApi]

export const CrawlModeEnumApi = {
    Single: 'single',
    Sitemap: 'sitemap',
    SameOrigin: 'same_origin',
    GithubRepo: 'github_repo',
} as const

export interface KnowledgeSourceApi {
    readonly id: string
    readonly team_id: number
    readonly name: string
    readonly source_type: KnowledgeSourceSourceTypeEnumApi
    readonly status: KnowledgeSourceStatusEnumApi
    readonly error_message: string
    /** Number of documents belonging to this source. */
    readonly document_count: number
    /** Number of chunks belonging to this source. */
    readonly chunk_count: number
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly source_url: string
    /** @nullable */
    readonly last_refresh_at: string | null
    readonly last_refresh_status: LastRefreshStatusEnumApi
    readonly last_refresh_error: string
    readonly refresh_interval: RefreshIntervalEnumApi
    /**
     * When the background coordinator will next auto-refresh this source. Null for manual sources or sources never refreshed.
     * @nullable
     */
    readonly next_refresh_at: string | null
    /** True when at least one document in this source was flagged unsafe by the content classifier and is therefore excluded from agent search. */
    readonly has_unsafe_documents: boolean
    /** Semantic-index state of this source. A `ready` source serves keyword (full-text) search immediately, but semantic search needs a background job to classify and embed its documents, which can take up to an hour. `pending` — at least one document is still awaiting classification or embedding. `completed` — every eligible document has been submitted to the embedding pipeline. `disabled` — the organization has not approved AI data processing, so embeddings never run and search stays keyword-only. Only meaningful while `status` is `ready`. */
    readonly embedding_status: EmbeddingStatusEnumApi
    readonly crawl_mode: CrawlModeEnumApi
    readonly crawl_config: unknown
    readonly original_filename: string
    readonly file_content_type: string
    /** @nullable */
    readonly file_size_bytes: number | null
    readonly always_include: boolean
}

export interface PaginatedKnowledgeSourceListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: KnowledgeSourceApi[]
}

export interface CreateTextSourceApi {
    /**
     * Short human label for the source. Shown in the settings list and in agent citations.
     * @maxLength 255
     */
    name: string
    /** Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL/file support in Stage 2/3. */
    text: string
    /** When true, this source's content is injected into every support reply prompt as general context (tone, policies, direction). */
    always_include?: boolean
}

/**
 * PATCH payload for text sources. All fields optional, at least one
 * required. `text` triggers a re-chunk; `name` or `always_include` alone does not.
 */
export interface PatchedUpdateTextSourceApi {
    /**
     * New human label for the source.
     * @maxLength 255
     */
    name?: string
    /** Replacement text. Omit to keep the existing content. */
    text?: string
    /** When true, this source's content is injected into every support reply prompt as general context. */
    always_include?: boolean
}

export type BusinessKnowledgeDocumentsWindowListParams = {
    /**
     * Zero-based chunk ordinal to center the window on (from a search result).
     */
    around_ordinal: number
    /**
     * Number of chunks before and after the center to include. Defaults to 5, clamped to [0, 15].
     */
    radius?: number
}

export type BusinessKnowledgeDocumentsSearchListParams = {
    /**
     * Maximum number of ranked chunks to return. Defaults to 10, capped at 20.
     */
    limit?: number
    /**
     * Natural-language search query. Runs hybrid (semantic + full-text) retrieval over all SAFE, READY knowledge chunks in this project.
     */
    query: string
    /**
     * When true, rerank search results with a listwise LLM pass for better relevance. Defaults to false (RRF order only). Falls back to RRF order on rerank failure.
     */
    rerank?: boolean
}

export type BusinessKnowledgeGapSuggestionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * When provided, returns per-ticket gap rows instead of aggregated view. Requires `ticket:read` scope in addition to `business_knowledge:read`.
     */
    ticket_id?: string
}

export type BusinessKnowledgeSourcesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BusinessKnowledgeSourcesTextRetrieve200 = {
    text?: string
}
