/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface _SummaryApi {
    /** Inclusive UTC start of the spend window resolved from the request. */
    date_from: string
    /** Exclusive UTC end of the spend window resolved from the request. */
    date_to: string
    /** The `ai_product` filter applied to tool / model / trace breakdowns — echoes the request `product`. */
    product: string
    /** Total LLM cost in USD across every `ai_product` for the user — independent of the `product` filter. */
    total_cost_usd: number
    /** Total $ai_generation + $ai_embedding events captured across every product. */
    event_count: number
    /** Total cost in USD for the product filter. Matches the cost summed across `by_tool` / `by_model` for the scoped slice. */
    scoped_cost_usd: number
    /** Total $ai_generation + $ai_embedding events for the scoped slice. */
    scoped_event_count: number
}

export interface _ProductBreakdownRowApi {
    /**
     * Value of the `ai_product` property on the event (e.g. `posthog_code`, `background_agents`). Null when unset.
     * @nullable
     */
    product: string | null
    /** Number of $ai_generation + $ai_embedding events for this product. */
    event_count: number
    /** Total cost in USD for this product over the lookback window. */
    cost_usd: number
}

export interface _ProductBreakdownApi {
    /** Rows of spend by product, ordered by cost descending. */
    items: _ProductBreakdownRowApi[]
    /** True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them. */
    truncated: boolean
}

export interface _ToolBreakdownRowApi {
    /**
     * Individual tool name from `$ai_tools_called` (split on `,` since multi-tool generations store a comma-separated list). Null = pure text response with no tool call.
     * @nullable
     */
    tool: string | null
    /** Number of $ai_generation events whose tool list includes this tool. */
    generation_count: number
    /** Sum of `$ai_total_cost_usd` for generations whose tool list includes this tool. Multi-tool generations contribute their full cost to every tool they invoked, so this sum can exceed `summary.scoped_cost_usd`. Prefer `share_of_scoped` for headline percentages — it's computed per row and doesn't require the totals to reconcile. */
    cost_usd: number
    /** This tool's share of `summary.scoped_cost_usd`, expressed as a float in `[0, 1]`. Independent per row, so co-occurring tools can each show a substantial share — the headline number to present (e.g. `'Bash drove 47% of your spend'`). */
    share_of_scoped: number
    /** Average `$ai_input_tokens` across these generations — high values signal context bloat per call. */
    avg_input_tokens: number
}

export interface _ToolBreakdownApi {
    /** Rows of spend by tool, ordered by cost descending. */
    items: _ToolBreakdownRowApi[]
    /** True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them. */
    truncated: boolean
}

export interface _ModelBreakdownRowApi {
    /**
     * Value of the `$ai_model` property.
     * @nullable
     */
    model: string | null
    /** Number of $ai_generation + $ai_embedding events. */
    generation_count: number
    /** Total cost in USD for this model. */
    cost_usd: number
    /** Sum of `$ai_input_tokens` for this model. */
    input_tokens: number
    /** Sum of `$ai_output_tokens` for this model. */
    output_tokens: number
}

export interface _ModelBreakdownApi {
    /** Rows of spend by model, ordered by cost descending. */
    items: _ModelBreakdownRowApi[]
    /** True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them. */
    truncated: boolean
}

export interface _DayBreakdownRowApi {
    /** UTC calendar day the events fall on (`toDate(timestamp)`). */
    day: string
    /** Number of $ai_generation + $ai_embedding events on this day for the scoped product. */
    event_count: number
    /** Total cost in USD on this day for the scoped product. */
    cost_usd: number
}

export interface _DayBreakdownApi {
    /** One row per UTC day that has events, ordered by day ascending. Days with no events are omitted — zero-fill client-side when rendering a continuous series. */
    items: _DayBreakdownRowApi[]
    /** Effectively always false: `by_day` ignores `limit` because truncating a time series by cost would be meaningless, and the 90-day window cap already bounds the series length. */
    truncated: boolean
}

export interface _BucketBreakdownRowApi {
    /** UTC start of the time bucket the events fall in (`toStartOfInterval(timestamp, ...)`). */
    bucket_start: string
    /** Number of $ai_generation + $ai_embedding events in this bucket for the scoped product. */
    event_count: number
    /** Total cost in USD in this bucket (sum of `$ai_total_cost_usd`). Authoritative: the component columns below can sum to less than this when the cost breakdown was unavailable for some events; render any remainder as uncategorized rather than assuming the components reconcile. */
    cost_usd: number
    /** Cost of uncached (full-price) input tokens in USD (sum of `$ai_input_cost_usd`). */
    input_cost_usd: number
    /** Cost of output tokens in USD (sum of `$ai_output_cost_usd`). */
    output_cost_usd: number
    /** Cost of prompt-cache reads in USD (sum of `$ai_cache_read_cost_usd`). */
    cache_read_cost_usd: number
    /** Cost of prompt-cache writes in USD (sum of `$ai_cache_creation_cost_usd`). A spike here with near-zero cache reads is the signature of a cold session being revived: the full conversation context is re-written to the cache at the cache-write rate instead of being read back cheaply. */
    cache_creation_cost_usd: number
    /** Sum of uncached `$ai_input_tokens` in this bucket. */
    input_tokens: number
    /** Sum of `$ai_output_tokens` in this bucket. */
    output_tokens: number
    /** Sum of `$ai_cache_read_input_tokens` (prompt tokens served from cache) in this bucket. */
    cache_read_input_tokens: number
    /** Sum of `$ai_cache_creation_input_tokens` (prompt tokens written to cache) in this bucket. */
    cache_creation_input_tokens: number
}

export interface _BucketBreakdownApi {
    /** One row per UTC time bucket that has events, ordered by bucket start ascending. Buckets with no events are omitted; zero-fill client-side when rendering a continuous series. */
    items: _BucketBreakdownRowApi[]
    /** Bucket size in minutes the series was computed at; echoes the request `bucket_minutes`. */
    bucket_minutes: number
    /** Effectively always false: `by_bucket` ignores `limit` because truncating a time series by cost would be meaningless, and the 600-bucket window cap already bounds the series length. */
    truncated: boolean
}

export interface _TopTraceRowApi {
    /**
     * `$ai_trace_id` of the session — opaque string scoped to the originating product. Format is not stable: most are UUIDs but some SDK wrappers emit JSON-shaped strings like `{"device_id":"...","session_id":"..."}`. Callers should treat this as an opaque identifier (URL-encode before linking to a trace view).
     * @nullable
     */
    trace_id: string | null
    /** Number of $ai_generation events in this trace. */
    generation_count: number
    /** Total cost in USD for this trace. */
    cost_usd: number
    /**
     * Timestamp of the earliest event in this trace.
     * @nullable
     */
    started_at: string | null
}

export interface _TopTracesApi {
    /** Rows of top traces by cost, ordered by cost descending. */
    items: _TopTraceRowApi[]
    /** True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them. */
    truncated: boolean
}

/**
 * Structured personal LLM spend analysis for the requesting user.
 */
export interface PersonalSpendAnalysisResponseApi {
    /** High-level totals for the lookback window. */
    summary: _SummaryApi
    /** Spend grouped by the `ai_product` property — always across all products, never filtered. */
    by_product: _ProductBreakdownApi
    /** Spend grouped by tool. Scoped to `product` when set. */
    by_tool: _ToolBreakdownApi
    /** Spend grouped by `$ai_model`. Scoped to `product` when set. */
    by_model: _ModelBreakdownApi
    /** Spend grouped by UTC day, ordered ascending. Scoped to `product`. Not subject to `limit`. */
    by_day: _DayBreakdownApi
    /** Spend grouped by UTC time bucket with per-bucket cost/token components, ordered ascending. Scoped to `product`. Only present when the request set `bucket_minutes`. */
    by_bucket?: _BucketBreakdownApi
    /** Deprecated — always returns `{items: [], truncated: false}`. Trace IDs are opaque strings that aren't actionable in the UI. Kept in the response shape so existing consumers don't crash; remove your rendering of this field and we'll drop it from the response entirely in a follow-up. */
    top_traces: _TopTracesApi
}

/**
 * DRF's default error envelope — `{ "detail": str }` — typed for the OpenAPI schema.
 */
export interface _ErrorResponseApi {
    /** Human-readable error description from DRF. */
    detail: string
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface DatasetItemApi {
    readonly id: string
    dataset: string
    input?: unknown
    output?: unknown
    metadata?: unknown
    /**
     * @maxLength 255
     * @nullable
     */
    ref_trace_id?: string | null
    /** @nullable */
    ref_timestamp?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_source_id?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedDatasetItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DatasetItemApi[]
}

export interface PatchedDatasetItemApi {
    readonly id?: string
    dataset?: string
    input?: unknown
    output?: unknown
    metadata?: unknown
    /**
     * @maxLength 255
     * @nullable
     */
    ref_trace_id?: string | null
    /** @nullable */
    ref_timestamp?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_source_id?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi
    readonly team?: number
}

export interface DatasetApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    description?: string | null
    metadata?: unknown
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedDatasetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DatasetApi[]
}

export interface PatchedDatasetApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    description?: string | null
    metadata?: unknown
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_by?: UserBasicApi
    readonly team?: number
}

export interface EvaluationRunRequestApi {
    /** UUID of the evaluation to run. */
    evaluation_id: string
    /** UUID of the $ai_generation event to evaluate. */
    target_event_id: string
    /** ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup). */
    timestamp: string
    /** Event name. Defaults to '$ai_generation'. */
    event?: string
    /**
     * Distinct ID of the event (optional, improves lookup performance).
     * @nullable
     */
    distinct_id?: string | null
}

/**
 * * `active` - Active
 * * `paused` - Paused
 * * `error` - Error
 */
export type EvaluationStatusEnumApi = (typeof EvaluationStatusEnumApi)[keyof typeof EvaluationStatusEnumApi]

export const EvaluationStatusEnumApi = {
    Active: 'active',
    Paused: 'paused',
    Error: 'error',
} as const

/**
 * * `provider_key_required` - No provider API key configured
 * * `trial_limit_reached` - Trial evaluation limit reached
 * * `model_not_allowed` - Model not available on the trial plan
 * * `provider_key_deleted` - Provider API key was deleted
 * * `no_default_model` - No default model available for the selected provider
 * * `provider_key_invalid` - Provider API key is invalid
 * * `provider_key_permission_denied` - Provider API key lacks model access
 * * `provider_key_quota_exceeded` - Provider API key quota exceeded
 * * `provider_key_rate_limited` - Provider API key is rate limited
 * * `model_not_found` - Model not found
 * * `hog_error` - Hog evaluation code failed
 */
export type StatusReasonEnumApi = (typeof StatusReasonEnumApi)[keyof typeof StatusReasonEnumApi]

export const StatusReasonEnumApi = {
    ProviderKeyRequired: 'provider_key_required',
    TrialLimitReached: 'trial_limit_reached',
    ModelNotAllowed: 'model_not_allowed',
    ProviderKeyDeleted: 'provider_key_deleted',
    NoDefaultModel: 'no_default_model',
    ProviderKeyInvalid: 'provider_key_invalid',
    ProviderKeyPermissionDenied: 'provider_key_permission_denied',
    ProviderKeyQuotaExceeded: 'provider_key_quota_exceeded',
    ProviderKeyRateLimited: 'provider_key_rate_limited',
    ModelNotFound: 'model_not_found',
    HogError: 'hog_error',
} as const

/**
 * * `llm_judge` - LLM as a judge
 * * `hog` - Hog
 * * `sentiment` - Sentiment analysis
 */
export type EvaluationTypeEnumApi = (typeof EvaluationTypeEnumApi)[keyof typeof EvaluationTypeEnumApi]

export const EvaluationTypeEnumApi = {
    LlmJudge: 'llm_judge',
    Hog: 'hog',
    Sentiment: 'sentiment',
} as const

/**
 * * `boolean` - Boolean (Pass/Fail)
 * * `sentiment` - Sentiment
 */
export type OutputTypeEnumApi = (typeof OutputTypeEnumApi)[keyof typeof OutputTypeEnumApi]

export const OutputTypeEnumApi = {
    Boolean: 'boolean',
    Sentiment: 'sentiment',
} as const

export type EvaluationConditionApiPropertiesItem = { [key: string]: unknown }

/**
 * A trigger condition set controlling which generations an evaluation runs on.
 */
export interface EvaluationConditionApi {
    /**
     * Stable identifier for this condition set.
     * @maxLength 100
     */
    id: string
    /**
     * Percentage (0-100) of matching events to sample for this evaluation. Defaults to 100.
     * @minimum 0
     * @maximum 100
     */
    rollout_percentage?: number
    /** Property filters (event or person) that scope which generations match this condition set. */
    properties?: EvaluationConditionApiPropertiesItem[]
}

/**
 * * `generation` - Generation
 * * `trace` - Trace
 */
export type EvaluationTargetEnumApi = (typeof EvaluationTargetEnumApi)[keyof typeof EvaluationTargetEnumApi]

export const EvaluationTargetEnumApi = {
    Generation: 'generation',
    Trace: 'trace',
} as const

/**
 * * `openai` - Openai
 * * `anthropic` - Anthropic
 * * `gemini` - Gemini
 * * `openrouter` - Openrouter
 * * `fireworks` - Fireworks
 * * `azure_openai` - Azure OpenAI
 * * `together_ai` - Together AI
 * * `minimax` - MiniMax
 * * `zeabur` - Zeabur AI Hub
 */
export type LLMProviderEnumApi = (typeof LLMProviderEnumApi)[keyof typeof LLMProviderEnumApi]

export const LLMProviderEnumApi = {
    Openai: 'openai',
    Anthropic: 'anthropic',
    Gemini: 'gemini',
    Openrouter: 'openrouter',
    Fireworks: 'fireworks',
    AzureOpenai: 'azure_openai',
    TogetherAi: 'together_ai',
    Minimax: 'minimax',
    Zeabur: 'zeabur',
} as const

/**
 * Nested serializer for model configuration.
 */
export interface ModelConfigurationApi {
    provider: LLMProviderEnumApi
    /** @maxLength 100 */
    model: string
    /**
     * Team provider key to run this eval with (same provider as `provider`). Leave null only for brief pre-key testing; real evals should set it.
     * @nullable
     */
    provider_key_id?: string | null
    /** @nullable */
    readonly provider_key_name: string | null
}

/**
 * Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}.
 */
export type EvaluationApiEvaluationConfig =
    | {
          /**
           * Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.
           * @minLength 1
           */
          prompt: string
      }
    | {
          /**
           * Hog source code. Must return true (pass), false (fail), or null for N/A.
           * @minLength 1
           */
          source: string
      }
    | {
          /** Classify sentiment from user messages in the generation input. */
          source?: 'user_messages'
      }

/**
 * Output config. For 'boolean' output_type: {allows_na} to permit N/A results.
 */
export type EvaluationApiOutputConfig = {
    /** Whether the evaluation can return N/A for non-applicable generations. */
    allows_na?: boolean
}

/**
 * Target-specific config. For 'trace' target: {window_seconds}. Empty for 'generation'.
 */
export type EvaluationApiTargetConfig = {
    /**
     * For 'trace' target: seconds to wait after the first matching generation before evaluating the whole trace. Captured when the run is scheduled — editing it does not change trace runs already in flight.
     * @minimum 10
     * @maximum 7200
     */
    window_seconds?: number
}

export interface EvaluationApi {
    readonly id: string
    /**
     * Name of the evaluation.
     * @maxLength 400
     */
    name: string
    /** Optional description of what this evaluation checks. */
    description?: string
    /** Whether the evaluation runs automatically on new $ai_generation events. */
    enabled?: boolean
    readonly status: EvaluationStatusEnumApi
    readonly status_reason: StatusReasonEnumApi | null
    /**
     * Additional detail for the current system-disabled status. This is only populated when the detail is safe to show in the evaluation UI.
     * @nullable
     */
    readonly status_reason_detail: string | null
    /** 'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment.
     *
     * * `llm_judge` - LLM as a judge
     * * `hog` - Hog
     * * `sentiment` - Sentiment analysis */
    evaluation_type: EvaluationTypeEnumApi
    /** Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}. */
    evaluation_config?: EvaluationApiEvaluationConfig
    /** Output format. Use 'boolean' for pass/fail evaluations and 'sentiment' for sentiment analysis.
     *
     * * `boolean` - Boolean (Pass/Fail)
     * * `sentiment` - Sentiment */
    output_type: OutputTypeEnumApi
    /** Output config. For 'boolean' output_type: {allows_na} to permit N/A results. */
    output_config?: EvaluationApiOutputConfig
    /** Trigger conditions that filter which events are evaluated. OR between condition sets, AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` (0-100, defaults to 100) is the sampling field the dispatcher reads. */
    conditions?: EvaluationConditionApi[]
    /** What the evaluation runs on. 'generation' evaluates each matching $ai_generation event individually. 'trace' evaluates the whole trace once: the first matching generation schedules a run that waits for the trace to settle, then evaluates all of its events together. Condition filters still match individual generations — a trace is evaluated when any of its generations matches, and sampling applies per trace.
     *
     * * `generation` - Generation
     * * `trace` - Trace */
    target?: EvaluationTargetEnumApi
    /** Target-specific config. For 'trace' target: {window_seconds}. Empty for 'generation'. */
    target_config?: EvaluationApiTargetConfig
    model_configuration?: ModelConfigurationApi | null
    readonly created_at: string
    readonly updated_at: string
    readonly created_by: UserBasicApi
    /** Set to true to soft-delete the evaluation. */
    deleted?: boolean
}

export interface PaginatedEvaluationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EvaluationApi[]
}

/**
 * Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}.
 */
export type PatchedEvaluationApiEvaluationConfig =
    | {
          /**
           * Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.
           * @minLength 1
           */
          prompt: string
      }
    | {
          /**
           * Hog source code. Must return true (pass), false (fail), or null for N/A.
           * @minLength 1
           */
          source: string
      }
    | {
          /** Classify sentiment from user messages in the generation input. */
          source?: 'user_messages'
      }

/**
 * Output config. For 'boolean' output_type: {allows_na} to permit N/A results.
 */
export type PatchedEvaluationApiOutputConfig = {
    /** Whether the evaluation can return N/A for non-applicable generations. */
    allows_na?: boolean
}

/**
 * Target-specific config. For 'trace' target: {window_seconds}. Empty for 'generation'.
 */
export type PatchedEvaluationApiTargetConfig = {
    /**
     * For 'trace' target: seconds to wait after the first matching generation before evaluating the whole trace. Captured when the run is scheduled — editing it does not change trace runs already in flight.
     * @minimum 10
     * @maximum 7200
     */
    window_seconds?: number
}

export interface PatchedEvaluationApi {
    readonly id?: string
    /**
     * Name of the evaluation.
     * @maxLength 400
     */
    name?: string
    /** Optional description of what this evaluation checks. */
    description?: string
    /** Whether the evaluation runs automatically on new $ai_generation events. */
    enabled?: boolean
    readonly status?: EvaluationStatusEnumApi
    readonly status_reason?: StatusReasonEnumApi | null
    /**
     * Additional detail for the current system-disabled status. This is only populated when the detail is safe to show in the evaluation UI.
     * @nullable
     */
    readonly status_reason_detail?: string | null
    /** 'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment.
     *
     * * `llm_judge` - LLM as a judge
     * * `hog` - Hog
     * * `sentiment` - Sentiment analysis */
    evaluation_type?: EvaluationTypeEnumApi
    /** Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}. */
    evaluation_config?: PatchedEvaluationApiEvaluationConfig
    /** Output format. Use 'boolean' for pass/fail evaluations and 'sentiment' for sentiment analysis.
     *
     * * `boolean` - Boolean (Pass/Fail)
     * * `sentiment` - Sentiment */
    output_type?: OutputTypeEnumApi
    /** Output config. For 'boolean' output_type: {allows_na} to permit N/A results. */
    output_config?: PatchedEvaluationApiOutputConfig
    /** Trigger conditions that filter which events are evaluated. OR between condition sets, AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` (0-100, defaults to 100) is the sampling field the dispatcher reads. */
    conditions?: EvaluationConditionApi[]
    /** What the evaluation runs on. 'generation' evaluates each matching $ai_generation event individually. 'trace' evaluates the whole trace once: the first matching generation schedules a run that waits for the trace to settle, then evaluates all of its events together. Condition filters still match individual generations — a trace is evaluated when any of its generations matches, and sampling applies per trace.
     *
     * * `generation` - Generation
     * * `trace` - Trace */
    target?: EvaluationTargetEnumApi
    /** Target-specific config. For 'trace' target: {window_seconds}. Empty for 'generation'. */
    target_config?: PatchedEvaluationApiTargetConfig
    model_configuration?: ModelConfigurationApi | null
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
    /** Set to true to soft-delete the evaluation. */
    deleted?: boolean
}

export type TestHogRequestApiConditionsItem = { [key: string]: unknown }

export interface TestHogRequestApi {
    /**
     * Hog source code to test. Must return a boolean (true = pass, false = fail) or null for N/A.
     * @minLength 1
     */
    source: string
    /**
     * Number of recent $ai_generation events to test against (1–10, default 5).
     * @minimum 1
     * @maximum 10
     */
    sample_count?: number
    /** Whether the evaluation can return N/A for non-applicable generations. */
    allows_na?: boolean
    /** Optional trigger conditions to filter which events are sampled. */
    conditions?: TestHogRequestApiConditionsItem[]
}

export interface TestHogResultItemApi {
    /** UUID of the $ai_generation event. */
    event_uuid: string
    /**
     * Trace ID if available.
     * @nullable
     */
    trace_id?: string | null
    /** First 200 chars of the generation input. */
    input_preview: string
    /** First 200 chars of the generation output. */
    output_preview: string
    /**
     * True = pass, False = fail, null = N/A or error.
     * @nullable
     */
    result: boolean | null
    /**
     * Hog evaluation reasoning string, if any.
     * @nullable
     */
    reasoning: string | null
    /**
     * Error message if the Hog code raised an exception.
     * @nullable
     */
    error: string | null
}

export interface TestHogResponseApi {
    results: TestHogResultItemApi[]
    /** Optional message, e.g. when no recent events were found. */
    message?: string
}

export type ClusteringConfigApiEventFiltersItem = { [key: string]: unknown }

export interface ClusteringConfigApi {
    /** PostHog property filters that scope automated clustering jobs. Empty array means no saved filters. */
    event_filters: ClusteringConfigApiEventFiltersItem[]
    readonly created_at: string
    readonly updated_at: string
}

export type ClusteringConfigSetEventFiltersApiEventFiltersItem = { [key: string]: unknown }

export interface ClusteringConfigSetEventFiltersApi {
    /** PostHog property filters to save for automated clustering jobs. Pass an empty array to clear filters. */
    event_filters: ClusteringConfigSetEventFiltersApiEventFiltersItem[]
}

/**
 * * `trace` - trace
 * * `generation` - generation
 * * `evaluation` - evaluation
 */
export type AnalysisLevelEnumApi = (typeof AnalysisLevelEnumApi)[keyof typeof AnalysisLevelEnumApi]

export const AnalysisLevelEnumApi = {
    Trace: 'trace',
    Generation: 'generation',
    Evaluation: 'evaluation',
} as const

export interface ClusteringJobApi {
    readonly id: string
    /** @maxLength 100 */
    name: string
    analysis_level: AnalysisLevelEnumApi
    event_filters?: unknown
    enabled?: boolean
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedClusteringJobListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ClusteringJobApi[]
}

export interface PatchedClusteringJobApi {
    readonly id?: string
    /** @maxLength 100 */
    name?: string
    analysis_level?: AnalysisLevelEnumApi
    event_filters?: unknown
    enabled?: boolean
    readonly created_at?: string
    readonly updated_at?: string
}

export type ClusteringRunRequestApiEventFiltersItem = { [key: string]: unknown }

/**
 * * `none` - none
 * * `l2` - l2
 */
export type EmbeddingNormalizationEnumApi =
    (typeof EmbeddingNormalizationEnumApi)[keyof typeof EmbeddingNormalizationEnumApi]

export const EmbeddingNormalizationEnumApi = {
    None: 'none',
    L2: 'l2',
} as const

/**
 * * `none` - none
 * * `umap` - umap
 * * `pca` - pca
 */
export type DimensionalityReductionMethodEnumApi =
    (typeof DimensionalityReductionMethodEnumApi)[keyof typeof DimensionalityReductionMethodEnumApi]

export const DimensionalityReductionMethodEnumApi = {
    None: 'none',
    Umap: 'umap',
    Pca: 'pca',
} as const

/**
 * * `hdbscan` - hdbscan
 * * `kmeans` - kmeans
 */
export type ClusteringMethodEnumApi = (typeof ClusteringMethodEnumApi)[keyof typeof ClusteringMethodEnumApi]

export const ClusteringMethodEnumApi = {
    Hdbscan: 'hdbscan',
    Kmeans: 'kmeans',
} as const

/**
 * * `umap` - umap
 * * `pca` - pca
 * * `tsne` - tsne
 */
export type VisualizationMethodEnumApi = (typeof VisualizationMethodEnumApi)[keyof typeof VisualizationMethodEnumApi]

export const VisualizationMethodEnumApi = {
    Umap: 'umap',
    Pca: 'pca',
    Tsne: 'tsne',
} as const

/**
 * Serializer for clustering workflow request parameters.
 */
export interface ClusteringRunRequestApi {
    /**
     * Number of days to look back for traces
     * @minimum 1
     * @maximum 90
     */
    lookback_days?: number
    /**
     * Maximum number of traces to sample for clustering
     * @minimum 20
     * @maximum 10000
     */
    max_samples?: number
    /** Embedding normalization method: 'none' (raw embeddings) or 'l2' (L2 normalize before clustering)
     *
     * * `none` - none
     * * `l2` - l2 */
    embedding_normalization?: EmbeddingNormalizationEnumApi
    /** Dimensionality reduction method: 'none' (cluster on raw), 'umap', or 'pca'
     *
     * * `none` - none
     * * `umap` - umap
     * * `pca` - pca */
    dimensionality_reduction_method?: DimensionalityReductionMethodEnumApi
    /**
     * Target dimensions for dimensionality reduction (ignored if method is 'none')
     * @minimum 2
     * @maximum 500
     */
    dimensionality_reduction_ndims?: number
    /** Clustering algorithm: 'hdbscan' (density-based, auto-determines k) or 'kmeans' (centroid-based)
     *
     * * `hdbscan` - hdbscan
     * * `kmeans` - kmeans */
    clustering_method?: ClusteringMethodEnumApi
    /**
     * Minimum cluster size as fraction of total samples (e.g., 0.02 = 2%)
     * @minimum 0.02
     * @maximum 0.5
     */
    min_cluster_size_fraction?: number
    /**
     * HDBSCAN min_samples parameter (higher = more conservative clustering)
     * @minimum 1
     * @maximum 100
     */
    hdbscan_min_samples?: number
    /**
     * Minimum number of clusters to try for k-means
     * @minimum 2
     * @maximum 50
     */
    kmeans_min_k?: number
    /**
     * Maximum number of clusters to try for k-means
     * @minimum 2
     * @maximum 100
     */
    kmeans_max_k?: number
    /**
     * Optional label/tag for the clustering run (used as suffix in run_id for tracking experiments)
     * @maxLength 50
     */
    run_label?: string
    /** Method for 2D scatter plot visualization: 'umap', 'pca', or 'tsne'
     *
     * * `umap` - umap
     * * `pca` - pca
     * * `tsne` - tsne */
    visualization_method?: VisualizationMethodEnumApi
    /** Property filters to scope which traces are included in clustering (PostHog standard format) */
    event_filters?: ClusteringRunRequestApiEventFiltersItem[]
    /**
     * If provided, use this clustering job's analysis_level and event_filters instead of request params
     * @nullable
     */
    clustering_job_id?: string | null
}

/**
 * * `unknown` - Unknown
 * * `ok` - Ok
 * * `invalid` - Invalid
 * * `error` - Error
 */
export type LLMProviderKeyStateEnumApi = (typeof LLMProviderKeyStateEnumApi)[keyof typeof LLMProviderKeyStateEnumApi]

export const LLMProviderKeyStateEnumApi = {
    Unknown: 'unknown',
    Ok: 'ok',
    Invalid: 'invalid',
    Error: 'error',
} as const

export interface LLMProviderKeyApi {
    readonly id: string
    provider: LLMProviderEnumApi
    /** @maxLength 255 */
    name: string
    readonly state: LLMProviderKeyStateEnumApi
    /** @nullable */
    readonly error_message: string | null
    api_key?: string
    readonly api_key_masked: string
    /** Azure OpenAI endpoint URL */
    azure_endpoint?: string
    /**
     * Azure OpenAI API version
     * @maxLength 20
     */
    api_version?: string
    /**
     * Azure endpoint (read-only, for display)
     * @nullable
     */
    readonly azure_endpoint_display: string | null
    /**
     * Azure API version (read-only, for display)
     * @nullable
     */
    readonly api_version_display: string | null
    set_as_active?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly last_used_at: string | null
}

export interface EvaluationConfigApi {
    /** Cap on trial runs — a getting-started affordance only, not for ongoing evals (use the team's own key). */
    readonly trial_eval_limit: number
    /** Trial runs consumed (getting-started affordance only). */
    readonly trial_evals_used: number
    /** Trial runs remaining — a getting-started affordance only; evals should use the team's own provider key. */
    readonly trial_evals_remaining: number
    /** True while this team keeps PostHog-funded trial inference during the deprecation window (i.e. it is mid-trial and the cutoff has not passed). False means the team must use its own provider key. */
    readonly trial_grandfathered: boolean
    /** Timestamp after which trial evaluations are fully removed and every team must use its own provider key. */
    readonly trial_deprecation_date: string
    /** Provider key used to run llm_judge evals; null if none configured yet. */
    readonly active_provider_key: LLMProviderKeyApi | null
    /** Timestamp when the evaluation config row was created. */
    readonly created_at: string
    /** Timestamp when the evaluation config row was last modified. */
    readonly updated_at: string
}

export interface EvaluationConfigSetActiveKeyRequestApi {
    /** UUID of an existing LLM provider key (state must be 'ok') to mark as the active key for running llm_judge evaluations team-wide. */
    key_id: string
}

/**
 * * `scheduled` - Scheduled
 * * `every_n` - Every N
 */
export type EvaluationReportFrequencyEnumApi =
    (typeof EvaluationReportFrequencyEnumApi)[keyof typeof EvaluationReportFrequencyEnumApi]

export const EvaluationReportFrequencyEnumApi = {
    Scheduled: 'scheduled',
    EveryN: 'every_n',
} as const

export interface EvaluationReportApi {
    readonly id: string
    /** UUID of the evaluation this report config belongs to. */
    evaluation: string
    /** How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule.
     *
     * * `scheduled` - Scheduled
     * * `every_n` - Every N */
    frequency?: EvaluationReportFrequencyEnumApi
    /** RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is 'scheduled'; ignored otherwise. */
    rrule?: string
    /**
     * Read-only anchor datetime used to expand scheduled reports. The server sets this automatically when a report is switched to scheduled mode.
     * @nullable
     */
    readonly starts_at: string | null
    /** Read-only timezone used for scheduled reports. Evaluation reports use UTC. */
    readonly timezone_name: string
    /** @nullable */
    readonly next_delivery_date: string | null
    /** List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team. */
    delivery_targets?: unknown
    /**
     * Maximum number of evaluation runs included in each report. Defaults to 200.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    max_sample_size?: number
    /** Whether report delivery is active. Disabled configs do not fire. */
    enabled?: boolean
    /** Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use enabled=false to stop deliveries. */
    readonly deleted: boolean
    /** @nullable */
    readonly last_delivered_at: string | null
    /** Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt. */
    report_prompt_guidance?: string
    /**
     * Number of new evaluation results that triggers a report (every_n mode only). Min 100, max 10000. Defaults to 100. Required when frequency is 'every_n'.
     * @minimum 100
     * @maximum 10000
     * @nullable
     */
    trigger_threshold?: number | null
    /**
     * Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.
     * @minimum 60
     * @maximum 1440
     */
    cooldown_minutes?: number
    /**
     * Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.
     * @minimum 1
     * @maximum 24
     */
    daily_run_cap?: number
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
}

export interface PaginatedEvaluationReportListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EvaluationReportApi[]
}

export interface EvaluationReportUpdateApi {
    readonly id: string
    /** UUID of the evaluation this report config belongs to. */
    readonly evaluation: string
    /** How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule.
     *
     * * `scheduled` - Scheduled
     * * `every_n` - Every N */
    frequency?: EvaluationReportFrequencyEnumApi
    /** RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is 'scheduled'; ignored otherwise. */
    rrule?: string
    /**
     * Read-only anchor datetime used to expand scheduled reports. The server sets this automatically when a report is switched to scheduled mode.
     * @nullable
     */
    readonly starts_at: string | null
    /** Read-only timezone used for scheduled reports. Evaluation reports use UTC. */
    readonly timezone_name: string
    /** @nullable */
    readonly next_delivery_date: string | null
    /** List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team. */
    delivery_targets?: unknown
    /**
     * Maximum number of evaluation runs included in each report. Defaults to 200.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    max_sample_size?: number
    /** Whether report delivery is active. Disabled configs do not fire. */
    enabled?: boolean
    /** Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use enabled=false to stop deliveries. */
    readonly deleted: boolean
    /** @nullable */
    readonly last_delivered_at: string | null
    /** Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt. */
    report_prompt_guidance?: string
    /**
     * Number of new evaluation results that triggers a report (every_n mode only). Min 100, max 10000. Defaults to 100. Required when frequency is 'every_n'.
     * @minimum 100
     * @maximum 10000
     * @nullable
     */
    trigger_threshold?: number | null
    /**
     * Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.
     * @minimum 60
     * @maximum 1440
     */
    cooldown_minutes?: number
    /**
     * Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.
     * @minimum 1
     * @maximum 24
     */
    daily_run_cap?: number
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
}

export interface PatchedEvaluationReportUpdateApi {
    readonly id?: string
    /** UUID of the evaluation this report config belongs to. */
    readonly evaluation?: string
    /** How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule.
     *
     * * `scheduled` - Scheduled
     * * `every_n` - Every N */
    frequency?: EvaluationReportFrequencyEnumApi
    /** RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is 'scheduled'; ignored otherwise. */
    rrule?: string
    /**
     * Read-only anchor datetime used to expand scheduled reports. The server sets this automatically when a report is switched to scheduled mode.
     * @nullable
     */
    readonly starts_at?: string | null
    /** Read-only timezone used for scheduled reports. Evaluation reports use UTC. */
    readonly timezone_name?: string
    /** @nullable */
    readonly next_delivery_date?: string | null
    /** List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team. */
    delivery_targets?: unknown
    /**
     * Maximum number of evaluation runs included in each report. Defaults to 200.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    max_sample_size?: number
    /** Whether report delivery is active. Disabled configs do not fire. */
    enabled?: boolean
    /** Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use enabled=false to stop deliveries. */
    readonly deleted?: boolean
    /** @nullable */
    readonly last_delivered_at?: string | null
    /** Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt. */
    report_prompt_guidance?: string
    /**
     * Number of new evaluation results that triggers a report (every_n mode only). Min 100, max 10000. Defaults to 100. Required when frequency is 'every_n'.
     * @minimum 100
     * @maximum 10000
     * @nullable
     */
    trigger_threshold?: number | null
    /**
     * Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.
     * @minimum 60
     * @maximum 1440
     */
    cooldown_minutes?: number
    /**
     * Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.
     * @minimum 1
     * @maximum 24
     */
    daily_run_cap?: number
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
}

/**
 * * `pending` - Pending
 * * `delivered` - Delivered
 * * `partial_failure` - Partial Failure
 * * `failed` - Failed
 */
export type DeliveryStatusEnumApi = (typeof DeliveryStatusEnumApi)[keyof typeof DeliveryStatusEnumApi]

export const DeliveryStatusEnumApi = {
    Pending: 'pending',
    Delivered: 'delivered',
    PartialFailure: 'partial_failure',
    Failed: 'failed',
} as const

export interface EvaluationReportRunApi {
    /** UUID of this report run. */
    readonly id: string
    /** UUID of the report config that generated this run. */
    readonly report: string
    /** Generated report content (markdown or structured text). */
    readonly content: unknown
    /** Run metadata including model used, token counts, and generation stats. */
    readonly metadata: unknown
    /** Start of the evaluation window covered by this report. */
    readonly period_start: string
    /** End of the evaluation window covered by this report. */
    readonly period_end: string
    /** 'pending', 'delivered', or 'failed'.
     *
     * * `pending` - Pending
     * * `delivered` - Delivered
     * * `partial_failure` - Partial Failure
     * * `failed` - Failed */
    readonly delivery_status: DeliveryStatusEnumApi
    /** List of delivery error messages if delivery failed. */
    readonly delivery_errors: unknown
    readonly created_at: string
}

export interface PaginatedEvaluationReportRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EvaluationReportRunApi[]
}

/**
 * * `all` - all
 * * `pass` - pass
 * * `fail` - fail
 * * `na` - na
 */
export type FilterEnumApi = (typeof FilterEnumApi)[keyof typeof FilterEnumApi]

export const FilterEnumApi = {
    All: 'all',
    Pass: 'pass',
    Fail: 'fail',
    Na: 'na',
} as const

/**
 * Request serializer for evaluation summary - accepts IDs only, fetches data server-side.
 */
export interface EvaluationSummaryRequestApi {
    /** UUID of the evaluation config to summarize */
    evaluation_id: string
    /** Filter type to apply ('all', 'pass', 'fail', or 'na')
     *
     * * `all` - all
     * * `pass` - pass
     * * `fail` - fail
     * * `na` - na */
    filter?: FilterEnumApi
    /**
     * Optional: specific generation IDs to include in summary (max 250)
     * @maxItems 250
     */
    generation_ids?: string[]
    /** If true, bypass cache and generate a fresh summary */
    force_refresh?: boolean
}

export interface EvaluationPatternApi {
    title: string
    description: string
    frequency: string
    example_generation_ids: string[]
}

export interface EvaluationSummaryStatisticsApi {
    total_analyzed: number
    pass_count: number
    fail_count: number
    na_count: number
}

export interface EvaluationSummaryResponseApi {
    overall_assessment: string
    pass_patterns: EvaluationPatternApi[]
    fail_patterns: EvaluationPatternApi[]
    na_patterns: EvaluationPatternApi[]
    recommendations: string[]
    statistics: EvaluationSummaryStatisticsApi
}

export interface LLMModelInfoApi {
    /** Provider-specific model identifier (e.g. 'gpt-4o-mini', 'claude-3-5-sonnet-20241022'). */
    id: string
    /** True if the model can run without a provider key on PostHog-funded trial credits. Only true for teams still grandfathered into the deprecating trial; every other team must use its own key. */
    posthog_available: boolean
}

export interface LLMModelsListResponseApi {
    /** Models supported for the requested provider. */
    models: LLMModelInfoApi[]
}

export interface OfflineExperimentItemsRequestApi {
    /** `$ai_experiment_id` whose offline-evaluation items to return. */
    experiment_id: string
    /**
     * Lower bound on `timestamp` (ISO-8601). Omit to leave the lower bound open.
     * @nullable
     */
    date_from?: string | null
    /**
     * Upper bound on `timestamp` (ISO-8601). Omit to leave the upper bound open.
     * @nullable
     */
    date_to?: string | null
}

export interface OfflineExperimentItemsResponseApi {
    /** Tuple-positional rows; positions match `RawOfflineExperimentMetricRow` in the frontend. */
    results: unknown[][]
}

export interface ParserRecipeApi {
    readonly id: string
    /**
     * Human-readable recipe name shown in the editor.
     * @maxLength 255
     */
    name: string
    /**
     * Raw YAML recipe source. Must parse as YAML; recipe semantics are compiled and validated client-side.
     * @maxLength 100000
     */
    source: string
    /** User who created the recipe. */
    readonly created_by: UserBasicApi | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedParserRecipeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ParserRecipeApi[]
}

export interface PatchedParserRecipeApi {
    readonly id?: string
    /**
     * Human-readable recipe name shown in the editor.
     * @maxLength 255
     */
    name?: string
    /**
     * Raw YAML recipe source. Must parse as YAML; recipe semantics are compiled and validated client-side.
     * @maxLength 100000
     */
    source?: string
    /** User who created the recipe. */
    readonly created_by?: UserBasicApi | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

export interface PaginatedLLMProviderKeyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMProviderKeyApi[]
}

export interface PatchedLLMProviderKeyApi {
    readonly id?: string
    provider?: LLMProviderEnumApi
    /** @maxLength 255 */
    name?: string
    readonly state?: LLMProviderKeyStateEnumApi
    /** @nullable */
    readonly error_message?: string | null
    api_key?: string
    readonly api_key_masked?: string
    /** Azure OpenAI endpoint URL */
    azure_endpoint?: string
    /**
     * Azure OpenAI API version
     * @maxLength 20
     */
    api_version?: string
    /**
     * Azure endpoint (read-only, for display)
     * @nullable
     */
    readonly azure_endpoint_display?: string | null
    /**
     * Azure API version (read-only, for display)
     * @nullable
     */
    readonly api_version_display?: string | null
    set_as_active?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly last_used_at?: string | null
}

export interface ReviewQueueItemApi {
    readonly id: string
    /** Review queue ID that currently owns this pending trace. */
    readonly queue_id: string
    /** Human-readable name of the queue that currently owns this pending trace. */
    readonly queue_name: string
    /** Trace ID currently pending review. */
    readonly trace_id: string
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** User who queued this trace. */
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedReviewQueueItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReviewQueueItemApi[]
}

export interface ReviewQueueItemCreateApi {
    /** Review queue ID that should own this pending trace. */
    queue_id: string
    /**
     * Trace ID to add to the selected review queue.
     * @maxLength 255
     */
    trace_id: string
}

export interface PatchedReviewQueueItemUpdateApi {
    /** Review queue ID that should own this pending trace. */
    queue_id?: string
}

export interface ReviewQueueApi {
    readonly id: string
    /** Human-readable queue name. */
    readonly name: string
    /** Number of pending traces currently assigned to this queue. */
    readonly pending_item_count: number
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** User who created this review queue. */
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedReviewQueueListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReviewQueueApi[]
}

export interface ReviewQueueCreateApi {
    /**
     * Human-readable queue name.
     * @maxLength 255
     */
    name: string
}

export interface PatchedReviewQueueUpdateApi {
    /**
     * Human-readable queue name.
     * @maxLength 255
     */
    name?: string
}

/**
 * * `categorical` - categorical
 * * `numeric` - numeric
 * * `boolean` - boolean
 */
export type ExperimentMetricKindEnumApi = (typeof ExperimentMetricKindEnumApi)[keyof typeof ExperimentMetricKindEnumApi]

export const ExperimentMetricKindEnumApi = {
    Categorical: 'categorical',
    Numeric: 'numeric',
    Boolean: 'boolean',
} as const

export interface CategoricalScoreOptionApi {
    /**
     * Stable option key. Use lowercase letters, numbers, underscores, or hyphens.
     * @maxLength 128
     */
    key: string
    /**
     * Human-readable option label.
     * @maxLength 256
     */
    label: string
}

/**
 * * `single` - single
 * * `multiple` - multiple
 */
export type SelectionModeEnumApi = (typeof SelectionModeEnumApi)[keyof typeof SelectionModeEnumApi]

export const SelectionModeEnumApi = {
    Single: 'single',
    Multiple: 'multiple',
} as const

export interface CategoricalScoreDefinitionConfigApi {
    /** Ordered categorical options available to the scorer. */
    options: CategoricalScoreOptionApi[]
    /** Whether reviewers can select one option or multiple options. Defaults to `single`.
     *
     * * `single` - single
     * * `multiple` - multiple */
    selection_mode?: SelectionModeEnumApi
    /**
     * Optional minimum number of options that can be selected when `selection_mode` is `multiple`.
     * @minimum 1
     * @nullable
     */
    min_selections?: number | null
    /**
     * Optional maximum number of options that can be selected when `selection_mode` is `multiple`.
     * @minimum 1
     * @nullable
     */
    max_selections?: number | null
}

export interface NumericScoreDefinitionConfigApi {
    /**
     * Optional inclusive minimum score.
     * @nullable
     */
    min?: number | null
    /**
     * Optional inclusive maximum score.
     * @nullable
     */
    max?: number | null
    /**
     * Optional increment step for numeric input, for example 1 or 0.5.
     * @nullable
     */
    step?: number | null
}

export interface BooleanScoreDefinitionConfigApi {
    /** Optional label for a true value. */
    true_label?: string
    /** Optional label for a false value. */
    false_label?: string
}

export type ScoreDefinitionConfigApi =
    | CategoricalScoreDefinitionConfigApi
    | NumericScoreDefinitionConfigApi
    | BooleanScoreDefinitionConfigApi

export interface ScoreDefinitionApi {
    readonly id: string
    readonly name: string
    readonly description: string
    readonly kind: ExperimentMetricKindEnumApi
    readonly archived: boolean
    /** Current immutable configuration version number. */
    readonly current_version: number
    /**
     * UUID of the current version row. Matches `system.score_definitions.current_version_id` in HogQL.
     * @nullable
     */
    readonly current_version_id: string | null
    /** Current immutable scorer configuration. */
    readonly config: ScoreDefinitionConfigApi
    /** User who created the scorer. */
    readonly created_by: UserBasicApi | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly team: number
}

export interface PaginatedScoreDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ScoreDefinitionApi[]
}

export interface ScoreDefinitionCreateApi {
    /**
     * Human-readable scorer name.
     * @maxLength 255
     */
    name: string
    /**
     * Optional human-readable description.
     * @nullable
     */
    description?: string | null
    /** Scorer kind. This cannot be changed after creation.
     *
     * * `categorical` - categorical
     * * `numeric` - numeric
     * * `boolean` - boolean */
    kind: ExperimentMetricKindEnumApi
    /** New scorers are always created as active. */
    archived?: boolean
    /** Initial immutable scorer configuration. */
    config: ScoreDefinitionConfigApi
}

export interface PatchedScoreDefinitionMetadataApi {
    /**
     * Updated scorer name.
     * @maxLength 255
     */
    name?: string
    /**
     * Updated scorer description.
     * @nullable
     */
    description?: string | null
    /** Whether the scorer is archived. */
    archived?: boolean
}

export interface ScoreDefinitionNewVersionApi {
    /** Next immutable scorer configuration. */
    config: ScoreDefinitionConfigApi
    /**
     * Version number the caller observed before requesting this bump. If provided and it does not match the scorer's current version, the request fails with 409. Omit to skip the optimistic-concurrency check.
     * @minimum 1
     */
    base_version?: number
}

/**
 * * `trace` - trace
 * * `event` - event
 */
export type SummarizeTypeEnumApi = (typeof SummarizeTypeEnumApi)[keyof typeof SummarizeTypeEnumApi]

export const SummarizeTypeEnumApi = {
    Trace: 'trace',
    Event: 'event',
} as const

/**
 * * `minimal` - minimal
 * * `detailed` - detailed
 */
export type DetailModeValueEnumApi = (typeof DetailModeValueEnumApi)[keyof typeof DetailModeValueEnumApi]

export const DetailModeValueEnumApi = {
    Minimal: 'minimal',
    Detailed: 'detailed',
} as const

export interface SummarizeRequestApi {
    /** Type of entity to summarize. Inferred automatically when using trace_id or generation_id.
     *
     * * `trace` - trace
     * * `event` - event */
    summarize_type?: SummarizeTypeEnumApi
    /** Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points
     *
     * * `minimal` - minimal
     * * `detailed` - detailed */
    mode?: DetailModeValueEnumApi
    /** Data to summarize. For traces: {trace, hierarchy}. For events: {event}. Not required when using trace_id or generation_id. */
    data?: unknown
    /** Force regenerate summary, bypassing cache */
    force_refresh?: boolean
    /**
     * LLM model to use (defaults based on provider)
     * @nullable
     */
    model?: string | null
    /** Trace ID to summarize. The backend fetches the trace data automatically. Requires date_from for efficient lookup. */
    trace_id?: string
    /** Generation event UUID to summarize. The backend fetches the event data automatically. Requires date_from for efficient lookup. */
    generation_id?: string
    /**
     * Start of date range for ID-based lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d.
     * @nullable
     */
    date_from?: string | null
    /**
     * End of date range for ID-based lookup. Defaults to now.
     * @nullable
     */
    date_to?: string | null
}

export interface SummaryBulletApi {
    text: string
    line_refs: string
}

export interface InterestingNoteApi {
    text: string
    line_refs: string
}

export interface StructuredSummaryApi {
    /** Concise title (no longer than 10 words) summarizing the trace/event */
    title: string
    /** Mermaid flowchart code showing the main flow */
    flow_diagram: string
    /** Main summary bullets */
    summary_bullets: SummaryBulletApi[]
    /** Interesting notes (0-2 for minimal, more for detailed) */
    interesting_notes: InterestingNoteApi[]
}

export interface SummarizeResponseApi {
    /** Structured AI-generated summary with flow, bullets, and optional notes */
    summary: StructuredSummaryApi
    /** Line-numbered text representation that the summary references */
    text_repr: string
    /** Metadata about the summarization */
    metadata?: unknown
}

export interface BatchCheckRequestApi {
    /**
     * List of trace IDs to check for cached summaries
     * @maxItems 100
     */
    trace_ids: string[]
    /** Summary detail level to check for
     *
     * * `minimal` - minimal
     * * `detailed` - detailed */
    mode?: DetailModeValueEnumApi
    /**
     * LLM model used for cached summaries
     * @nullable
     */
    model?: string | null
}

export interface CachedSummaryApi {
    trace_id: string
    title: string
    cached?: boolean
}

export interface BatchCheckResponseApi {
    summaries: CachedSummaryApi[]
}

/**
 * * `$ai_generation` - $ai_generation
 * * `$ai_span` - $ai_span
 * * `$ai_embedding` - $ai_embedding
 * * `$ai_trace` - $ai_trace
 */
export type EventTypeEnumApi = (typeof EventTypeEnumApi)[keyof typeof EventTypeEnumApi]

export const EventTypeEnumApi = {
    AiGeneration: '$ai_generation',
    AiSpan: '$ai_span',
    AiEmbedding: '$ai_embedding',
    AiTrace: '$ai_trace',
} as const

export interface TextReprOptionsApi {
    /** Maximum length of generated text (default: 2000000) */
    max_length?: number
    /** Use truncation for long content within events (default: true) */
    truncated?: boolean
    /** Characters to show at start/end when truncating (default: 1000) */
    truncate_buffer?: number
    /** Use interactive markers for frontend vs plain text for backend/LLM (default: true) */
    include_markers?: boolean
    /** Show summary vs full tree hierarchy for traces (default: false) */
    collapsed?: boolean
    /** Include metadata in response */
    include_metadata?: boolean
    /** Include hierarchy information (for traces) */
    include_hierarchy?: boolean
    /** Maximum depth for hierarchical rendering */
    max_depth?: number
    /** Number of tools before collapsing the list (default: 5) */
    tools_collapse_threshold?: number
    /** Prefix each line with line number (default: false) */
    include_line_numbers?: boolean
}

export interface TextReprRequestApi {
    /** Type of LLM event to stringify
     *
     * * `$ai_generation` - $ai_generation
     * * `$ai_span` - $ai_span
     * * `$ai_embedding` - $ai_embedding
     * * `$ai_trace` - $ai_trace */
    event_type: EventTypeEnumApi
    /** Event data to stringify. For traces, should include 'trace' and 'hierarchy' fields. */
    data: unknown
    /** Optional configuration for text generation */
    options?: TextReprOptionsApi
}

export interface TextReprMetadataApi {
    event_type?: string
    event_id?: string
    trace_id?: string
    rendering: string
    char_count: number
    truncated: boolean
    error?: string
}

export interface TextReprResponseApi {
    /** Generated text representation of the event */
    text: string
    /** Metadata about the text representation */
    metadata: TextReprMetadataApi
}

export interface TraceReviewScoreApi {
    readonly id: string
    /** Stable scorer definition ID. */
    readonly definition_id: string
    /** Human-readable scorer name. */
    readonly definition_name: string
    /** Scorer kind for this saved score. */
    readonly definition_kind: string
    /** Whether the scorer is currently archived. */
    readonly definition_archived: boolean
    /** Immutable scorer version ID used to validate this score. */
    readonly definition_version_id: string
    /** Immutable scorer version number used to validate this score. */
    readonly definition_version: number
    /** Immutable scorer configuration snapshot used to validate this score. */
    readonly definition_config: ScoreDefinitionConfigApi
    /**
     * Categorical option keys selected for this score.
     * @nullable
     */
    readonly categorical_values: readonly string[] | null
    /**
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    readonly numeric_value: string | null
    /** @nullable */
    readonly boolean_value: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface TraceReviewApi {
    readonly id: string
    /** Trace ID for the review. */
    readonly trace_id: string
    /** Absolute URL to the trace this review is attached to. */
    readonly trace_url: string
    /**
     * Optional comment or reasoning for the review.
     * @nullable
     */
    readonly comment: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
    /** User who last saved this review. */
    readonly reviewed_by: UserBasicApi
    /** Saved scorer values for this review. */
    readonly scores: readonly TraceReviewScoreApi[]
    readonly team: number
}

export interface PaginatedTraceReviewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TraceReviewApi[]
}

export interface TraceReviewScoreWriteApi {
    /** Stable scorer definition ID. */
    definition_id: string
    /**
     * Optional immutable scorer version ID. Defaults to the scorer's current version.
     * @nullable
     */
    definition_version_id?: string | null
    /**
     * Categorical option keys selected for this score.
     * @minItems 1
     * @nullable
     * @items.maxLength 128
     */
    categorical_values?: string[] | null
    /**
     * Numeric value selected for this score.
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    numeric_value?: string | null
    /**
     * Boolean value selected for this score.
     * @nullable
     */
    boolean_value?: boolean | null
}

export interface TraceReviewCreateApi {
    /**
     * Trace ID for the review. Only one active review can exist per trace and team.
     * @maxLength 255
     */
    trace_id: string
    /**
     * Optional comment or reasoning for the review.
     * @nullable
     */
    comment?: string | null
    /** Full desired score set for this review. Omit scorers you want to leave blank. */
    scores?: TraceReviewScoreWriteApi[]
    /**
     * Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.
     * @nullable
     */
    queue_id?: string | null
}

export interface PatchedTraceReviewUpdateApi {
    /**
     * Trace ID for the review. Only one active review can exist per trace and team.
     * @maxLength 255
     */
    trace_id?: string
    /**
     * Optional comment or reasoning for the review.
     * @nullable
     */
    comment?: string | null
    /** Full desired score set for this review. Omit scorers you want to leave blank. */
    scores?: TraceReviewScoreWriteApi[]
    /**
     * Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.
     * @nullable
     */
    queue_id?: string | null
}

export interface TranslateRequestApi {
    /**
     * The text to translate
     * @maxLength 10000
     */
    text: string
    /**
     * Target language code (default: 'en' for English)
     * @maxLength 10
     */
    target_language?: string
}

export interface LLMPromptOutlineEntryApi {
    /**
     * Markdown heading level (1-6).
     * @minimum 1
     * @maximum 6
     */
    level: number
    /** Heading text with markdown link syntax preserved. */
    text: string
}

export interface LLMPromptListApi {
    readonly id: string
    /** Unique prompt name using letters, numbers, hyphens, and underscores only. */
    readonly name: string
    /** Prompt payload as JSON or string data. */
    readonly prompt: unknown
    readonly version: number
    /**
     * Optional note describing what changed in this version. Set when the version is published.
     * @nullable
     */
    readonly version_description: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
    readonly outline: readonly LLMPromptOutlineEntryApi[]
    readonly prompt_preview: string
    readonly prompt_size_bytes: number
}

export interface PaginatedLLMPromptListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMPromptListApi[]
}

export interface LLMPromptApi {
    readonly id: string
    /**
     * Unique prompt name using letters, numbers, hyphens, and underscores only.
     * @maxLength 255
     */
    name: string
    /** Prompt payload as JSON or string data. */
    prompt: unknown
    readonly version: number
    /**
     * Optional note describing what changed in this version. Set when the version is published.
     * @maxLength 400
     * @nullable
     */
    version_description?: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
    readonly outline: readonly LLMPromptOutlineEntryApi[]
}

export interface LLMPromptPublicApi {
    id: string
    name: string
    /** Full prompt content. Omitted when 'content=preview' or 'content=none'. */
    prompt?: unknown
    /** First 160 characters of the prompt. Only present when 'content=preview'. */
    prompt_preview?: string
    /** Flat list of markdown headings parsed from the prompt. Useful as a lightweight table of contents. */
    outline: LLMPromptOutlineEntryApi[]
    version: number
    created_at: string
    updated_at: string
    deleted: boolean
    is_latest: boolean
    latest_version: number
    version_count: number
    first_version_created_at: string
}

export interface LLMPromptEditOperationApi {
    /** Text to find in the current prompt. Must match exactly once. */
    old: string
    /** Replacement text. */
    new: string
}

export interface PatchedLLMPromptPublishApi {
    /** Full prompt payload to publish as a new version. Mutually exclusive with edits. */
    prompt?: unknown
    /** List of find/replace operations to apply to the current prompt version. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with prompt. */
    edits?: LLMPromptEditOperationApi[]
    /**
     * Latest version you are editing from. Used for optimistic concurrency checks.
     * @minimum 1
     */
    base_version?: number
    /**
     * Optional note describing what changed in this version. Shown in the version history.
     * @maxLength 400
     */
    version_description?: string
}

export interface LLMPromptDuplicateApi {
    /**
     * Name for the duplicated prompt. Must be unique and use only letters, numbers, hyphens, and underscores.
     * @maxLength 255
     */
    new_name: string
}

export interface LLMPromptVersionSummaryApi {
    readonly id: string
    readonly version: number
    /** @nullable */
    readonly version_description: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly is_latest: boolean
}

export interface LLMPromptResolveResponseApi {
    prompt: LLMPromptApi
    versions: LLMPromptVersionSummaryApi[]
    has_more: boolean
}

/**
 * * `llm` - LLM
 * * `hog` - Hog
 */
export type TaggerTypeEnumApi = (typeof TaggerTypeEnumApi)[keyof typeof TaggerTypeEnumApi]

export const TaggerTypeEnumApi = {
    Llm: 'llm',
    Hog: 'hog',
} as const

export interface TagDefinitionApi {
    /**
     * Tag identifier
     * @maxLength 100
     */
    name: string
    /**
     * Description to help the LLM classify
     * @maxLength 500
     */
    description?: string
}

export interface LLMTaggerConfigApi {
    /**
     * Prompt instructing the LLM how to tag generations
     * @minLength 1
     */
    prompt: string
    /** Available tags the LLM can assign */
    tags: TagDefinitionApi[]
    /**
     * Minimum number of tags to apply
     * @minimum 0
     */
    min_tags?: number
    /**
     * Maximum number of tags to apply (null = no limit)
     * @minimum 1
     * @nullable
     */
    max_tags?: number | null
}

export interface HogTaggerConfigApi {
    /**
     * Hog source code to classify a generation into tags.
     * @minLength 1
     */
    source: string
    /** Optional tag whitelist. Leave empty to allow any tag returned by the Hog code. */
    tags?: TagDefinitionApi[]
}

export type TaggerConfigApi = LLMTaggerConfigApi | HogTaggerConfigApi

export type TaggerConditionApiPropertiesItem = { [key: string]: unknown }

export interface TaggerConditionApi {
    /**
     * Stable identifier for this condition
     * @maxLength 100
     */
    id: string
    /**
     * Percentage of matching events to apply this condition to
     * @minimum 0
     * @maximum 100
     */
    rollout_percentage?: number
    /** Property filters that scope when this condition fires */
    properties?: TaggerConditionApiPropertiesItem[]
}

/**
 * Nested serializer for model configuration.
 */
export interface TaggerModelConfigurationApi {
    /** LLM provider to use for this tagger.
     *
     * * `openai` - Openai
     * * `anthropic` - Anthropic
     * * `gemini` - Gemini
     * * `openrouter` - Openrouter
     * * `fireworks` - Fireworks
     * * `azure_openai` - Azure OpenAI
     * * `together_ai` - Together AI
     * * `minimax` - MiniMax
     * * `zeabur` - Zeabur AI Hub */
    provider: LLMProviderEnumApi
    /**
     * Provider model identifier to use for this tagger.
     * @maxLength 100
     */
    model: string
    /**
     * Existing LLM provider key UUID for the current project. Do not invent this value; use a real provider key ID returned by PostHog, or omit/null when no provider key should be pinned.
     * @nullable
     */
    provider_key_id?: string | null
    /** @nullable */
    readonly provider_key_name: string | null
}

export interface TaggerApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    enabled?: boolean
    tagger_type?: TaggerTypeEnumApi
    /** Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}. */
    tagger_config: TaggerConfigApi
    /** Conditions that scope when the tagger runs */
    conditions?: TaggerConditionApi[]
    model_configuration?: TaggerModelConfigurationApi | null
    readonly created_at: string
    readonly updated_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
}

export interface PaginatedTaggerListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaggerApi[]
}

export interface TaggerModelConfigurationWriteApi {
    /** LLM provider to use for this tagger.
     *
     * * `openai` - Openai
     * * `anthropic` - Anthropic
     * * `gemini` - Gemini
     * * `openrouter` - Openrouter
     * * `fireworks` - Fireworks
     * * `azure_openai` - Azure OpenAI
     * * `together_ai` - Together AI
     * * `minimax` - MiniMax
     * * `zeabur` - Zeabur AI Hub */
    provider: LLMProviderEnumApi
    /**
     * Provider model identifier to use for this tagger.
     * @maxLength 100
     */
    model: string
    /**
     * Existing LLM provider key UUID for the current project. Do not invent this value; use a real provider key ID returned by PostHog, or omit/null when no provider key should be pinned.
     * @nullable
     */
    provider_key_id?: string | null
}

export interface TaggerCreateApi {
    /** @maxLength 400 */
    name: string
    description?: string
    enabled?: boolean
    tagger_type?: TaggerTypeEnumApi
    /** Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}. */
    tagger_config: TaggerConfigApi
    /** Conditions that scope when the tagger runs */
    conditions?: TaggerConditionApi[]
    model_configuration?: TaggerModelConfigurationWriteApi | null
}

export interface TaggerUpdateApi {
    /** @maxLength 400 */
    name: string
    description?: string
    enabled?: boolean
    tagger_type?: TaggerTypeEnumApi
    /** Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}. */
    tagger_config: TaggerConfigApi
    /** Conditions that scope when the tagger runs */
    conditions?: TaggerConditionApi[]
    model_configuration?: TaggerModelConfigurationWriteApi | null
    deleted?: boolean
}

export interface PatchedTaggerUpdateApi {
    /** @maxLength 400 */
    name?: string
    description?: string
    enabled?: boolean
    tagger_type?: TaggerTypeEnumApi
    /** Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}. */
    tagger_config?: TaggerConfigApi
    /** Conditions that scope when the tagger runs */
    conditions?: TaggerConditionApi[]
    model_configuration?: TaggerModelConfigurationWriteApi | null
    deleted?: boolean
}

export interface TestHogTaggerTagApi {
    /**
     * Tag identifier to allow in Hog test results.
     * @maxLength 100
     */
    name: string
    /**
     * Optional description for the tag.
     * @maxLength 500
     */
    description?: string
}

export interface TestHogTaggerRequestApi {
    /**
     * Hog source code to test. Return a tag name string, a list of tag name strings, or null.
     * @minLength 1
     */
    source: string
    /**
     * Number of recent $ai_generation events to test against (1-10, default 5).
     * @minimum 1
     * @maximum 10
     */
    sample_count?: number
    /** Optional tag whitelist. Returned tags outside this list are filtered out. */
    tags?: TestHogTaggerTagApi[]
}

export interface TestHogTaggerResultItemApi {
    /** UUID of the sampled $ai_generation event. */
    event_uuid: string
    /**
     * Trace ID if available.
     * @nullable
     */
    trace_id?: string | null
    /** First 200 characters of the generation input. */
    input_preview: string
    /** First 200 characters of the generation output. */
    output_preview: string
    /** Tag names returned by the Hog code. */
    tags: string[]
    /** Text written to stdout by the Hog code. */
    reasoning: string
    /**
     * Error message if the Hog code failed.
     * @nullable
     */
    error?: string | null
}

export interface TestHogTaggerResponseApi {
    /** Per-event Hog tagger test results. */
    results: TestHogTaggerResultItemApi[]
    /** Optional message, for example when no recent AI events were found. */
    message?: string
}

export type LlmAnalyticsPersonalSpendListParams = {
    /**
     * When set, additionally return a `by_bucket` breakdown: a time-ascending UTC cost series for the scoped product at this bucket size in minutes, with per-bucket cost split into uncached input / output / cache read / cache creation components plus the matching token sums. Supported bucket sizes: 5, 15, 30, 60. The window may span at most 600 buckets of the chosen size (e.g. 50 hours at 5-minute buckets).
     *
     * * `5` - 5
     * * `15` - 15
     * * `30` - 30
     * * `60` - 60
     */
    bucket_minutes?: LlmAnalyticsPersonalSpendListBucketMinutes
    /**
     * Start of the spend window. Accepts absolute dates (`2026-04-23`) or relative strings (`-7d`, `-1m`, etc.) — same parser used elsewhere in PostHog. Defaults to `-30d`. The window between `date_from` and `date_to` cannot exceed 90 days.
     * @minLength 1
     * @maxLength 32
     */
    date_from?: string
    /**
     * End of the spend window. Accepts the same formats as `date_from`. Defaults to `now` when omitted.
     * @maxLength 32
     * @nullable
     */
    date_to?: string | null
    /**
     * Maximum number of rows to return per breakdown (1-200, defaults to 50). Each breakdown returns up to this many rows ordered by cost descending. Per-breakdown `truncated: true` indicates more rows exist beyond the limit.
     * @minimum 1
     * @maximum 200
     */
    limit?: number
    /**
     * Required `ai_product` key to scope the tool / model / trace breakdowns to a single product. Only the following products are currently supported: posthog_code.
     * @minLength 1
     * @maxLength 64
     */
    product: string
    /**
     * If true, bypass the result cache and re-run the underlying queries against ClickHouse.
     */
    refresh?: boolean
}

export type LlmAnalyticsPersonalSpendListBucketMinutes =
    (typeof LlmAnalyticsPersonalSpendListBucketMinutes)[keyof typeof LlmAnalyticsPersonalSpendListBucketMinutes]

export const LlmAnalyticsPersonalSpendListBucketMinutes = {
    Number5: 5,
    Number15: 15,
    Number30: 30,
    Number60: 60,
} as const

export type DatasetItemsListParams = {
    /**
     * Filter by dataset ID
     */
    dataset?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DatasetsListParams = {
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Ordering
     *
     * * `created_at` - Created At
     * * `-created_at` - Created At (descending)
     * * `updated_at` - Updated At
     * * `-updated_at` - Updated At (descending)
     */
    order_by?: string[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}

export type EvaluationRunsCreate200 = { [key: string]: unknown }

export type EvaluationsListParams = {
    /**
     * Filter by enabled status
     */
    enabled?: boolean
    /**
     * Filter by evaluation type
     *
     * * `llm_judge` - LLM as a judge
     * * `hog` - Hog
     * * `sentiment` - Sentiment analysis
     */
    evaluation_type?: EvaluationsListEvaluationType
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Ordering
     *
     * * `created_at` - Created At
     * * `-created_at` - Created At (descending)
     * * `updated_at` - Updated At
     * * `-updated_at` - Updated At (descending)
     * * `name` - Name
     * * `-name` - Name (descending)
     */
    order_by?: string[]
    /**
     * Search in name or description
     */
    search?: string
}

export type EvaluationsListEvaluationType =
    (typeof EvaluationsListEvaluationType)[keyof typeof EvaluationsListEvaluationType]

export const EvaluationsListEvaluationType = {
    Hog: 'hog',
    LlmJudge: 'llm_judge',
    Sentiment: 'sentiment',
} as const

export type LlmAnalyticsClusteringJobsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsEvaluationReportsListParams = {
    /**
     * Only return report configs for this evaluation UUID.
     */
    evaluation?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsEvaluationReportsRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsEvaluationSummaryCreate400 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationSummaryCreate403 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationSummaryCreate404 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationSummaryCreate500 = { [key: string]: unknown }

export type LlmAnalyticsModelsRetrieveParams = {
    /**
     * Optional provider key UUID. When supplied, models reachable with that specific key are returned (useful for Azure OpenAI, where the deployment list depends on the configured endpoint). Must belong to the same provider as the `provider` parameter.
     */
    key_id?: string
    /**
     * LLM provider to list models for. Must be one of the supported providers.
     */
    provider: LlmAnalyticsModelsRetrieveProvider
}

export type LlmAnalyticsModelsRetrieveProvider =
    (typeof LlmAnalyticsModelsRetrieveProvider)[keyof typeof LlmAnalyticsModelsRetrieveProvider]

export const LlmAnalyticsModelsRetrieveProvider = {
    Anthropic: 'anthropic',
    AzureOpenai: 'azure_openai',
    Fireworks: 'fireworks',
    Gemini: 'gemini',
    Minimax: 'minimax',
    Openai: 'openai',
    Openrouter: 'openrouter',
    TogetherAi: 'together_ai',
    Zeabur: 'zeabur',
} as const

export type LlmAnalyticsOfflineEvaluationsExperimentItemsCreate400 = { [key: string]: unknown }

export type LlmAnalyticsOfflineEvaluationsExperimentItemsCreate500 = { [key: string]: unknown }

export type LlmAnalyticsParserRecipesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsProviderKeyValidationsCreate200 = { [key: string]: unknown }

export type LlmAnalyticsProviderKeysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsReviewQueueItemsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Order by `created_at` or `updated_at`.
     */
    order_by?: string
    /**
     * Filter by a specific review queue ID.
     */
    queue_id?: string
    /**
     * Search pending trace IDs.
     */
    search?: string
    /**
     * Filter by an exact trace ID.
     */
    trace_id?: string
    /**
     * Filter by multiple trace IDs separated by commas.
     */
    trace_id__in?: string
}

export type LlmAnalyticsReviewQueuesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    name?: string
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Order by `name`, `updated_at`, or `created_at`.
     */
    order_by?: string
    /**
     * Search review queue names.
     */
    search?: string
}

export type LlmAnalyticsScoreDefinitionsListParams = {
    /**
     * Filter by archived state.
     */
    archived?: boolean
    /**
     * Filter by scorer kind.
     */
    kind?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort by name, kind, created_at, updated_at, or current_version.
     */
    order_by?: string
    /**
     * Search scorers by name or description.
     */
    search?: string
}

export type LlmAnalyticsSummarizationCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate403 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate500 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationBatchCheckCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationBatchCheckCreate403 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate400 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate500 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate503 = { [key: string]: unknown }

export type LlmAnalyticsTraceReviewsListParams = {
    /**
     * Filter by a stable scorer definition ID.
     */
    definition_id?: string
    /**
     * Filter by multiple scorer definition IDs separated by commas.
     */
    definition_id__in?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Order by `updated_at` or `created_at`.
     */
    order_by?: string
    /**
     * Search trace IDs and comments.
     */
    search?: string
    /**
     * Filter by an exact trace ID.
     */
    trace_id?: string
    /**
     * Filter by multiple trace IDs separated by commas.
     */
    trace_id__in?: string
}

export type LlmAnalyticsTranslateCreate200 = { [key: string]: unknown }

export type LlmPromptsListParams = {
    /**
     * Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.
     *
     * * `full` - full
     * * `preview` - preview
     * * `none` - none
     * @minLength 1
     */
    content?: LlmPromptsListContent
    /**
     * Filter prompts by the ID of the user who created them.
     */
    created_by_id?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional substring filter applied to prompt names and prompt content.
     */
    search?: string
}

export type LlmPromptsListContent = (typeof LlmPromptsListContent)[keyof typeof LlmPromptsListContent]

export const LlmPromptsListContent = {
    Full: 'full',
    Preview: 'preview',
    None: 'none',
} as const

export type LlmPromptsNameRetrieveParams = {
    /**
     * Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.
     *
     * * `full` - full
     * * `preview` - preview
     * * `none` - none
     * @minLength 1
     */
    content?: LlmPromptsNameRetrieveContent
    /**
     * Specific prompt version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmPromptsNameRetrieveContent =
    (typeof LlmPromptsNameRetrieveContent)[keyof typeof LlmPromptsNameRetrieveContent]

export const LlmPromptsNameRetrieveContent = {
    Full: 'full',
    Preview: 'preview',
    None: 'none',
} as const

export type LlmPromptsResolveNameRetrieveParams = {
    /**
     * Return versions older than this version number. Mutually exclusive with offset.
     * @minimum 1
     */
    before_version?: number
    /**
     * Maximum number of versions to return per page (1-100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Zero-based offset into version history for pagination. Mutually exclusive with before_version.
     * @minimum 0
     */
    offset?: number
    /**
     * Specific prompt version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
    /**
     * Exact prompt version UUID to resolve. Can be used together with version for extra safety.
     */
    version_id?: string
}

export type TaggersListParams = {
    /**
     * Filter by enabled status
     */
    enabled?: boolean
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Ordering
     *
     * * `created_at` - Created At
     * * `-created_at` - Created At (descending)
     * * `updated_at` - Updated At
     * * `-updated_at` - Updated At (descending)
     * * `name` - Name
     * * `-name` - Name (descending)
     */
    order_by?: string[]
    /**
     * Search in name or description
     */
    search?: string
}
