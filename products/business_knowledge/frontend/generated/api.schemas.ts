/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type KnowledgeSourceDTOApiCrawlConfig = { [key: string]: unknown }

export interface KnowledgeSourceDTOApi {
    id: string
    team_id: number
    name: string
    source_type: string
    status: string
    error_message: string
    document_count: number
    chunk_count: number
    created_at: string
    /** @nullable */
    updated_at: string | null
    source_url?: string
    /** @nullable */
    last_refresh_at?: string | null
    last_refresh_status?: string
    last_refresh_error?: string
    crawl_mode?: string
    crawl_config?: KnowledgeSourceDTOApiCrawlConfig
    original_filename?: string
    file_content_type?: string
    /** @nullable */
    file_size_bytes?: number | null
}

export interface PaginatedKnowledgeSourceDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: KnowledgeSourceDTOApi[]
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
