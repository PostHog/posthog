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
    /** Fetched page URL. Empty for text and file sources. */
    readonly url: string
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
    /** Source type: text, URL, or file. */
    readonly source_type: string
    /** Title of the document this chunk belongs to. */
    readonly document_title: string
    /** Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure. */
    readonly heading_path: string
    /** The chunk's text content. */
    readonly content: string
    /** True when this chunk comes from a generated source learned from a past support ticket. */
    readonly is_generated: boolean
    /** Fetched page URL. Empty for text and file sources. */
    readonly url: string
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

export interface PlaygroundChatListApi {
    /** Playground chat id. */
    id: string
    /** First question, truncated. Empty until someone asks. */
    title: string
    /** When this chat was created. */
    created_at: string
    /** When this chat was last asked in. */
    updated_at: string
    /** True while an answer in this chat is still running. Another question in this chat returns 409 until it finishes. */
    has_open_turn: boolean
}

/**
 * * `running` - Running
 * * `completed` - Completed
 * * `failed` - Failed
 * * `cancelled` - Cancelled
 */
export type SandboxPollStatusEnumApi = (typeof SandboxPollStatusEnumApi)[keyof typeof SandboxPollStatusEnumApi]

export const SandboxPollStatusEnumApi = {
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

export interface SandboxSourceApi {
    /** Source reference the reply relies on. */
    ref: string
    /** Short excerpt that supports the reply. */
    excerpt: string
}

/**
 * * `business-knowledge-documents-search` - Search
 * * `business-knowledge-document-window-retrieve` - Window
 * * `business-knowledge-repositories-search` - Repository search
 * * `business-knowledge-repositories-file-retrieve` - Repository file
 */
export type SandboxToolNameEnumApi = (typeof SandboxToolNameEnumApi)[keyof typeof SandboxToolNameEnumApi]

export const SandboxToolNameEnumApi = {
    BusinessKnowledgeDocumentsSearch: 'business-knowledge-documents-search',
    BusinessKnowledgeDocumentWindowRetrieve: 'business-knowledge-document-window-retrieve',
    BusinessKnowledgeRepositoriesSearch: 'business-knowledge-repositories-search',
    BusinessKnowledgeRepositoriesFileRetrieve: 'business-knowledge-repositories-file-retrieve',
} as const

export interface SandboxSearchApi {
    /** Business knowledge tool the agent called.
     *
     * * `business-knowledge-documents-search` - Search
     * * `business-knowledge-document-window-retrieve` - Window
     * * `business-knowledge-repositories-search` - Repository search
     * * `business-knowledge-repositories-file-retrieve` - Repository file */
    tool: SandboxToolNameEnumApi
    /** Tool input the agent sent. */
    input: string
}

export interface SandboxRunApi {
    /** Sandbox task id. */
    task_id: string
    /** Latest run id for this task. */
    run_id: string
    /** running while the agent works. completed carries reply and sources. failed and cancelled carry error.
     *
     * * `running` - Running
     * * `completed` - Completed
     * * `failed` - Failed
     * * `cancelled` - Cancelled */
    status: SandboxPollStatusEnumApi
    /**
     * Answer text when status is completed. Null otherwise.
     * @nullable
     */
    reply: string | null
    /** Sources cited in a completed answer. Empty when the run has not completed. */
    sources: SandboxSourceApi[]
    /** Business knowledge search and window calls observed in the run log. */
    searches: SandboxSearchApi[]
    /**
     * Why the run did not produce an answer. Null while running and on a completed answer.
     * @nullable
     */
    error: string | null
    /** True when the run log contains an exact docs-search call. That tool is not granted to this sandbox. */
    docs_search_called: boolean
}

export interface PlaygroundTurnApi {
    /** Turn id. */
    id: string
    /** Question that started this turn's sandbox run. */
    question: string
    /** Sandbox task id for this turn. */
    task_id: string
    /** Order of this turn in the chat, starting at 0. */
    position: number
    /** Current sandbox run for this turn. Null when the run cannot be loaded. */
    run: SandboxRunApi | null
    /**
     * Why this turn could not be loaded. Null when run is present.
     * @nullable
     */
    error: string | null
}

export interface PlaygroundChatApi {
    /** Playground chat id. */
    id: string
    /** First question, truncated. Empty until someone asks. */
    title: string
    /** When this chat was created. */
    created_at: string
    /** When this chat was last asked in. */
    updated_at: string
    /** True while an answer in this chat is still running. Another question in this chat returns 409 until it finishes. */
    has_open_turn: boolean
    /** Questions in this chat, oldest first. Each turn's answer comes from its sandbox run. */
    turns: PlaygroundTurnApi[]
}

export interface SandboxQuestionApi {
    /**
     * Question to answer from this project's business knowledge. Blank questions are rejected. Maximum 4000 characters.
     * @maxLength 4000
     */
    question: string
}

export interface RepositoryConnectApi {
    /** Id of a GitHub integration on this environment. */
    integration_id: number
}

export interface RepositoryConnectionApi {
    /** True when a GitHub installation is connected for this environment. */
    connected: boolean
    /**
     * Connected GitHub integration id, or null when GitHub is not connected.
     * @nullable
     */
    integration_id: number | null
    /** GitHub account name for the connected installation. Empty when GitHub is not connected. */
    integration_name: string
    /** Lowercased owner/repo names business knowledge is allowed to read. */
    repos: string[]
}

export interface RepositoryFileApi {
    /** Lowercased owner/repo. */
    repo: string
    /** File path that was read. */
    path: string
    /** Permalink for this file at the cached commit. Cite this when you use the file. */
    url: string
    /** File text, cut off at 32,000 characters. */
    content: string
    /** True when content was cut off at 32,000 characters. */
    truncated: boolean
}

/**
 * * `path` - Path
 * * `readme` - Readme
 */
export type RepositoryHitKindEnumApi = (typeof RepositoryHitKindEnumApi)[keyof typeof RepositoryHitKindEnumApi]

export const RepositoryHitKindEnumApi = {
    Path: 'path',
    Readme: 'readme',
} as const

export interface RepositorySearchHitApi {
    /** Lowercased owner/repo the hit came from. */
    repo: string
    /** File path. Empty for a README hit. */
    path: string
    /** Permalink for the hit. Cite this when you use the hit. */
    url: string
    /** path is a file name match. readme is a short excerpt of the repository README.
     *
     * * `path` - Path
     * * `readme` - Readme */
    kind: RepositoryHitKindEnumApi
    /** Short README excerpt. Empty for a path hit. */
    excerpt: string
}

/**
 * * `ready` - Ready
 * * `warming` - Warming
 */
export type RepositoryCacheStatusEnumApi =
    (typeof RepositoryCacheStatusEnumApi)[keyof typeof RepositoryCacheStatusEnumApi]

export const RepositoryCacheStatusEnumApi = {
    Ready: 'ready',
    Warming: 'warming',
} as const

export interface RepositoryCacheStateApi {
    /** Lowercased owner/repo. */
    repo: string
    /** True when the cached file list is incomplete because the repository has too many files. */
    tree_truncated: boolean
    /** ready means the file list was cached recently. warming means a refresh was just queued.
     *
     * * `ready` - Ready
     * * `warming` - Warming */
    cache_status: RepositoryCacheStatusEnumApi
}

export interface RepositorySearchResponseApi {
    /** Path matches, then README excerpts. */
    results: RepositorySearchHitApi[]
    /** Cache state for each repository that was searched. */
    repositories: RepositoryCacheStateApi[]
}

export interface RepositorySelectionApi {
    /**
     * owner/repo names to allow. At most 20. Replaces the current list.
     * @maxItems 20
     */
    repos: string[]
}

export interface SandboxRunStartedApi {
    /** Sandbox task id. Poll this id until the run finishes. */
    task_id: string
    /** Run id for this question. */
    run_id: string
}

export interface BusinessKnowledgeSettingsApi {
    /** When true, PostHog learns reusable knowledge from public human replies on resolved support tickets. Requires Support to be enabled for this environment. */
    learn_from_support_enabled: boolean
    /** Whether Support is enabled for this environment. Learning cannot be turned on while this is false. */
    readonly support_enabled: boolean
}

export interface PatchedBusinessKnowledgeSettingsUpdateApi {
    /** When true, PostHog learns reusable knowledge from public human replies on resolved support tickets. Rejected when Support is off for this environment. */
    learn_from_support_enabled?: boolean
}

/**
 * * `text` - Text
 * * `url` - URL
 * * `file` - File
 */
export type SourceTypeEnumApi = (typeof SourceTypeEnumApi)[keyof typeof SourceTypeEnumApi]

export const SourceTypeEnumApi = {
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
export type SourceStatusEnumApi = (typeof SourceStatusEnumApi)[keyof typeof SourceStatusEnumApi]

export const SourceStatusEnumApi = {
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
export type RefreshStatusEnumApi = (typeof RefreshStatusEnumApi)[keyof typeof RefreshStatusEnumApi]

export const RefreshStatusEnumApi = {
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
    readonly source_type: SourceTypeEnumApi
    /** Whether PostHog manages this source with knowledge learned from resolved support tickets. */
    readonly is_generated: boolean
    readonly status: SourceStatusEnumApi
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
    readonly last_refresh_status: RefreshStatusEnumApi
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
    /**
     * Support ticket number this learned source came from. Null for sources you added yourself.
     * @nullable
     */
    readonly learned_from_ticket_number: number | null
    /**
     * App URL of the originating support ticket. Null for sources you added yourself.
     * @nullable
     */
    readonly learned_from_ticket_url: string | null
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

/**
 * * `unknown` - Unknown
 * * `safe` - Safe
 * * `unsafe` - Unsafe
 */
export type SafetyVerdictEnumApi = (typeof SafetyVerdictEnumApi)[keyof typeof SafetyVerdictEnumApi]

export const SafetyVerdictEnumApi = {
    Unknown: 'unknown',
    Safe: 'safe',
    Unsafe: 'unsafe',
} as const

export interface KnowledgeSourceDocumentApi {
    /** Document id. */
    readonly id: string
    /** Fetched page URL after redirects. Empty for text and file documents. */
    readonly url: string
    /** Page title extracted while indexing. Falls back to empty when the page had none. */
    readonly title: string
    /** Content-safety verdict. Only `safe` documents are included in search. `unknown` is still waiting on classification.
     *
     * * `unknown` - Unknown
     * * `safe` - Safe
     * * `unsafe` - Unsafe */
    readonly safety_verdict: SafetyVerdictEnumApi
}

export interface PaginatedKnowledgeSourceDocumentListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: KnowledgeSourceDocumentApi[]
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

export type BusinessKnowledgeRepositoriesFileRetrieveParams = {
    /**
     * File path returned by the repository search.
     * @minLength 1
     */
    path: string
    /**
     * owner/repo to read. It must already be selected.
     * @minLength 1
     */
    repo: string
}

export type BusinessKnowledgeRepositoriesSearchParams = {
    /**
     * File names, path fragments, or identifiers to match. Not a full sentence.
     * @minLength 1
     */
    query: string
    /**
     * Limit the search to this owner/repo. It must already be selected. Omit to search every selected repository.
     */
    repo?: string
}

export type BusinessKnowledgeSourcesListParams = {
    /**
     * Filter by who added the source: human (you added it) or learned (from a resolved support ticket).
     */
    added_by?: BusinessKnowledgeSourcesListAddedBy
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Case-insensitive substring match against the source name and URL.
     */
    search?: string
    /**
     * Filter to a single source type (text, url, or file).
     */
    source_type?: BusinessKnowledgeSourcesListSourceType
}

export type BusinessKnowledgeSourcesListAddedBy =
    (typeof BusinessKnowledgeSourcesListAddedBy)[keyof typeof BusinessKnowledgeSourcesListAddedBy]

export const BusinessKnowledgeSourcesListAddedBy = {
    Human: 'human',
    Learned: 'learned',
} as const

export type BusinessKnowledgeSourcesListSourceType =
    (typeof BusinessKnowledgeSourcesListSourceType)[keyof typeof BusinessKnowledgeSourcesListSourceType]

export const BusinessKnowledgeSourcesListSourceType = {
    File: 'file',
    Text: 'text',
    Url: 'url',
} as const

export type BusinessKnowledgeSourcesDocumentsListParams = {
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
