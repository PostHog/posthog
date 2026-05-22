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
 * * `text` - Text
 * `url` - URL
 * `file` - File
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
 * `processing` - Processing
 * `ready` - Ready
 * `error` - Error
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
 * `not_modified` - Not modified
 * `error` - Error
 */
export type LastRefreshStatusEnumApi = (typeof LastRefreshStatusEnumApi)[keyof typeof LastRefreshStatusEnumApi]

export const LastRefreshStatusEnumApi = {
    Success: 'success',
    NotModified: 'not_modified',
    Error: 'error',
} as const

/**
 * * `single` - Single page
 * `sitemap` - Sitemap
 * `same_origin` - Same origin crawl
 * `github_repo` - GitHub repository
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
    readonly crawl_mode: CrawlModeEnumApi
    readonly crawl_config: unknown
    readonly original_filename: string
    readonly file_content_type: string
    /** @nullable */
    readonly file_size_bytes: number | null
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
}

/**
 * PATCH payload for text sources. Both fields optional, at least one
required. `text` triggers a re-chunk; `name` alone does not.
 */
export interface PatchedUpdateTextSourceApi {
    /**
     * New human label for the source.
     * @maxLength 255
     */
    name?: string
    /** Replacement text. Omit to keep the existing content. */
    text?: string
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
