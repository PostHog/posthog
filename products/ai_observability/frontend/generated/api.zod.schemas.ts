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

export const _SummaryApi = zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .describe('Inclusive UTC start of the spend window resolved from the request.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .describe('Exclusive UTC end of the spend window resolved from the request.'),
    product: zod
        .string()
        .describe(
            'The `ai_product` filter applied to tool \/ model \/ trace breakdowns — echoes the request `product`.'
        ),
    total_cost_usd: zod
        .number()
        .describe(
            'Total LLM cost in USD across every `ai_product` for the user — independent of the `product` filter.'
        ),
    event_count: zod.number().describe('Total $ai_generation + $ai_embedding events captured across every product.'),
    scoped_cost_usd: zod
        .number()
        .describe(
            'Total cost in USD for the product filter. Matches the cost summed across `by_tool` \/ `by_model` for the scoped slice.'
        ),
    scoped_event_count: zod.number().describe('Total $ai_generation + $ai_embedding events for the scoped slice.'),
})

export type _SummaryApi = zod.input<typeof _SummaryApi>
export type _SummaryApiOutput = zod.output<typeof _SummaryApi>

export const _ProductBreakdownRowApi = zod.object({
    product: zod
        .string()
        .nullable()
        .describe(
            'Value of the `ai_product` property on the event (e.g. `posthog_code`, `background_agents`). Null when unset.'
        ),
    event_count: zod.number().describe('Number of $ai_generation + $ai_embedding events for this product.'),
    cost_usd: zod.number().describe('Total cost in USD for this product over the lookback window.'),
})

export type _ProductBreakdownRowApi = zod.input<typeof _ProductBreakdownRowApi>
export type _ProductBreakdownRowApiOutput = zod.output<typeof _ProductBreakdownRowApi>

export const _ProductBreakdownApi = zod.object({
    items: zod.array(_ProductBreakdownRowApi).describe('Rows of spend by product, ordered by cost descending.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them.'
        ),
})

export type _ProductBreakdownApi = zod.input<typeof _ProductBreakdownApi>
export type _ProductBreakdownApiOutput = zod.output<typeof _ProductBreakdownApi>

export const _ToolBreakdownRowApi = zod.object({
    tool: zod
        .string()
        .nullable()
        .describe(
            'Individual tool name from `$ai_tools_called` (split on `,` since multi-tool generations store a comma-separated list). Null = pure text response with no tool call.'
        ),
    generation_count: zod.number().describe('Number of $ai_generation events whose tool list includes this tool.'),
    cost_usd: zod
        .number()
        .describe(
            "Sum of `$ai_total_cost_usd` for generations whose tool list includes this tool. Multi-tool generations contribute their full cost to every tool they invoked, so this sum can exceed `summary.scoped_cost_usd`. Prefer `share_of_scoped` for headline percentages — it's computed per row and doesn't require the totals to reconcile."
        ),
    share_of_scoped: zod
        .number()
        .describe(
            "This tool's share of `summary.scoped_cost_usd`, expressed as a float in `[0, 1]`. Independent per row, so co-occurring tools can each show a substantial share — the headline number to present (e.g. `'Bash drove 47% of your spend'`)."
        ),
    avg_input_tokens: zod
        .number()
        .describe('Average `$ai_input_tokens` across these generations — high values signal context bloat per call.'),
})

export type _ToolBreakdownRowApi = zod.input<typeof _ToolBreakdownRowApi>
export type _ToolBreakdownRowApiOutput = zod.output<typeof _ToolBreakdownRowApi>

export const _ToolBreakdownApi = zod.object({
    items: zod.array(_ToolBreakdownRowApi).describe('Rows of spend by tool, ordered by cost descending.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them.'
        ),
})

export type _ToolBreakdownApi = zod.input<typeof _ToolBreakdownApi>
export type _ToolBreakdownApiOutput = zod.output<typeof _ToolBreakdownApi>

export const _ModelBreakdownRowApi = zod.object({
    model: zod.string().nullable().describe('Value of the `$ai_model` property.'),
    generation_count: zod.number().describe('Number of $ai_generation + $ai_embedding events.'),
    cost_usd: zod.number().describe('Total cost in USD for this model.'),
    input_tokens: zod.number().describe('Sum of `$ai_input_tokens` for this model.'),
    output_tokens: zod.number().describe('Sum of `$ai_output_tokens` for this model.'),
})

export type _ModelBreakdownRowApi = zod.input<typeof _ModelBreakdownRowApi>
export type _ModelBreakdownRowApiOutput = zod.output<typeof _ModelBreakdownRowApi>

export const _ModelBreakdownApi = zod.object({
    items: zod.array(_ModelBreakdownRowApi).describe('Rows of spend by model, ordered by cost descending.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them.'
        ),
})

export type _ModelBreakdownApi = zod.input<typeof _ModelBreakdownApi>
export type _ModelBreakdownApiOutput = zod.output<typeof _ModelBreakdownApi>

export const _DayBreakdownRowApi = zod.object({
    day: zod.iso.date().describe('UTC calendar day the events fall on (`toDate(timestamp)`).'),
    event_count: zod
        .number()
        .describe('Number of $ai_generation + $ai_embedding events on this day for the scoped product.'),
    cost_usd: zod.number().describe('Total cost in USD on this day for the scoped product.'),
})

export type _DayBreakdownRowApi = zod.input<typeof _DayBreakdownRowApi>
export type _DayBreakdownRowApiOutput = zod.output<typeof _DayBreakdownRowApi>

export const _DayBreakdownApi = zod.object({
    items: zod
        .array(_DayBreakdownRowApi)
        .describe(
            'One row per UTC day that has events, ordered by day ascending. Days with no events are omitted — zero-fill client-side when rendering a continuous series.'
        ),
    truncated: zod
        .boolean()
        .describe(
            'Effectively always false: `by_day` ignores `limit` because truncating a time series by cost would be meaningless, and the 90-day window cap already bounds the series length.'
        ),
})

export type _DayBreakdownApi = zod.input<typeof _DayBreakdownApi>
export type _DayBreakdownApiOutput = zod.output<typeof _DayBreakdownApi>

export const _BucketBreakdownRowApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe('UTC start of the time bucket the events fall in (`toStartOfInterval(timestamp, ...)`).'),
    event_count: zod
        .number()
        .describe('Number of $ai_generation + $ai_embedding events in this bucket for the scoped product.'),
    cost_usd: zod
        .number()
        .describe(
            'Total cost in USD in this bucket (sum of `$ai_total_cost_usd`). Authoritative: the component columns below can sum to less than this when the cost breakdown was unavailable for some events; render any remainder as uncategorized rather than assuming the components reconcile.'
        ),
    input_cost_usd: zod
        .number()
        .describe(
            'Cost of uncached (full-price) input tokens in USD, derived per event as `$ai_input_cost_usd` minus the cache read\/write costs (the stored input cost includes them), clamped at zero. The four component columns are disjoint: they sum to `cost_usd` when the full breakdown is present, so they can be stacked without double counting cache costs.'
        ),
    output_cost_usd: zod.number().describe('Cost of output tokens in USD (sum of `$ai_output_cost_usd`).'),
    cache_read_cost_usd: zod.number().describe('Cost of prompt-cache reads in USD (sum of `$ai_cache_read_cost_usd`).'),
    cache_creation_cost_usd: zod
        .number()
        .describe(
            'Cost of prompt-cache writes in USD (sum of `$ai_cache_creation_cost_usd`). A spike here with near-zero cache reads is the signature of a cold session being revived: the full conversation context is re-written to the cache at the cache-write rate instead of being read back cheaply.'
        ),
    input_tokens: zod
        .number()
        .describe(
            "Sum of `$ai_input_tokens` in this bucket. Whether cached tokens are included follows the provider's reporting (`$ai_cache_reporting_exclusive`): Anthropic-style events exclude them, OpenAI-style events include them, so don't stack this with the cache token sums."
        ),
    output_tokens: zod.number().describe('Sum of `$ai_output_tokens` in this bucket.'),
    cache_read_input_tokens: zod
        .number()
        .describe('Sum of `$ai_cache_read_input_tokens` (prompt tokens served from cache) in this bucket.'),
    cache_creation_input_tokens: zod
        .number()
        .describe('Sum of `$ai_cache_creation_input_tokens` (prompt tokens written to cache) in this bucket.'),
})

export type _BucketBreakdownRowApi = zod.input<typeof _BucketBreakdownRowApi>
export type _BucketBreakdownRowApiOutput = zod.output<typeof _BucketBreakdownRowApi>

export const _BucketBreakdownApi = zod.object({
    items: zod
        .array(_BucketBreakdownRowApi)
        .describe(
            'One row per UTC time bucket that has events, ordered by bucket start ascending. Buckets with no events are omitted; zero-fill client-side when rendering a continuous series.'
        ),
    bucket_minutes: zod
        .number()
        .describe('Bucket size in minutes the series was computed at; echoes the request `bucket_minutes`.'),
    truncated: zod
        .boolean()
        .describe(
            'Effectively always false: `by_bucket` ignores `limit` because truncating a time series by cost would be meaningless, and the 600-bucket window cap already bounds the series length.'
        ),
})

export type _BucketBreakdownApi = zod.input<typeof _BucketBreakdownApi>
export type _BucketBreakdownApiOutput = zod.output<typeof _BucketBreakdownApi>

export const _TopTraceRowApi = zod.object({
    trace_id: zod
        .string()
        .nullable()
        .describe(
            '`$ai_trace_id` of the session — opaque string scoped to the originating product. Format is not stable: most are UUIDs but some SDK wrappers emit JSON-shaped strings like `{\"device_id\":\"...\",\"session_id\":\"...\"}`. Callers should treat this as an opaque identifier (URL-encode before linking to a trace view).'
        ),
    generation_count: zod.number().describe('Number of $ai_generation events in this trace.'),
    cost_usd: zod.number().describe('Total cost in USD for this trace.'),
    started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the earliest event in this trace.'),
})

export type _TopTraceRowApi = zod.input<typeof _TopTraceRowApi>
export type _TopTraceRowApiOutput = zod.output<typeof _TopTraceRowApi>

export const _TopTracesApi = zod.object({
    items: zod.array(_TopTraceRowApi).describe('Rows of top traces by cost, ordered by cost descending.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them.'
        ),
})

export type _TopTracesApi = zod.input<typeof _TopTracesApi>
export type _TopTracesApiOutput = zod.output<typeof _TopTracesApi>

export const PersonalSpendAnalysisResponseApi = zod
    .object({
        summary: _SummaryApi.describe('High-level totals for the lookback window.'),
        by_product: _ProductBreakdownApi.describe(
            'Spend grouped by the `ai_product` property — always across all products, never filtered.'
        ),
        by_tool: _ToolBreakdownApi.describe('Spend grouped by tool. Scoped to `product` when set.'),
        by_model: _ModelBreakdownApi.describe('Spend grouped by `$ai_model`. Scoped to `product` when set.'),
        by_day: _DayBreakdownApi.describe(
            'Spend grouped by UTC day, ordered ascending. Scoped to `product`. Not subject to `limit`.'
        ),
        by_bucket: _BucketBreakdownApi
            .optional()
            .describe(
                'Spend grouped by UTC time bucket with per-bucket cost\/token components, ordered ascending. Scoped to `product`. Only present when the request set `bucket_minutes`.'
            ),
        top_traces: _TopTracesApi.describe(
            "Deprecated — always returns `{items: [], truncated: false}`. Trace IDs are opaque strings that aren't actionable in the UI. Kept in the response shape so existing consumers don't crash; remove your rendering of this field and we'll drop it from the response entirely in a follow-up."
        ),
    })
    .describe('Structured personal LLM spend analysis for the requesting user.')

export type PersonalSpendAnalysisResponseApi = zod.input<typeof PersonalSpendAnalysisResponseApi>
export type PersonalSpendAnalysisResponseApiOutput = zod.output<typeof PersonalSpendAnalysisResponseApi>

export const _ErrorResponseApi = zod
    .object({
        detail: zod.string().describe('Human-readable error description from DRF.'),
    })
    .describe('DRF\'s default error envelope — `{ \"detail\": str }` — typed for the OpenAPI schema.')

export type _ErrorResponseApi = zod.input<typeof _ErrorResponseApi>
export type _ErrorResponseApiOutput = zod.output<typeof _ErrorResponseApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const datasetItemApiRefTraceIdMax = 255

export const datasetItemApiRefSourceIdMax = 255

export const DatasetItemApi = zod.object({
    id: zod.uuid(),
    dataset: zod.uuid(),
    input: zod.unknown().optional(),
    output: zod.unknown().optional(),
    metadata: zod.unknown().optional(),
    ref_trace_id: zod.string().max(datasetItemApiRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({ offset: true }).nullish(),
    ref_source_id: zod.string().max(datasetItemApiRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi,
    team: zod.number(),
})

export type DatasetItemApi = zod.input<typeof DatasetItemApi>
export type DatasetItemApiOutput = zod.output<typeof DatasetItemApi>

export const PaginatedDatasetItemListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DatasetItemApi),
})

export type PaginatedDatasetItemListApi = zod.input<typeof PaginatedDatasetItemListApi>
export type PaginatedDatasetItemListApiOutput = zod.output<typeof PaginatedDatasetItemListApi>

export const patchedDatasetItemApiRefTraceIdMax = 255

export const patchedDatasetItemApiRefSourceIdMax = 255

export const PatchedDatasetItemApi = zod.object({
    id: zod.uuid().optional(),
    dataset: zod.uuid().optional(),
    input: zod.unknown().optional(),
    output: zod.unknown().optional(),
    metadata: zod.unknown().optional(),
    ref_trace_id: zod.string().max(patchedDatasetItemApiRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({ offset: true }).nullish(),
    ref_source_id: zod.string().max(patchedDatasetItemApiRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
    created_by: UserBasicApi.optional(),
    team: zod.number().optional(),
})

export type PatchedDatasetItemApi = zod.input<typeof PatchedDatasetItemApi>
export type PatchedDatasetItemApiOutput = zod.output<typeof PatchedDatasetItemApi>

export const datasetApiNameMax = 400

export const DatasetApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(datasetApiNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    deleted: zod.boolean().nullish(),
    created_by: UserBasicApi,
    team: zod.number(),
})

export type DatasetApi = zod.input<typeof DatasetApi>
export type DatasetApiOutput = zod.output<typeof DatasetApi>

export const PaginatedDatasetListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DatasetApi),
})

export type PaginatedDatasetListApi = zod.input<typeof PaginatedDatasetListApi>
export type PaginatedDatasetListApiOutput = zod.output<typeof PaginatedDatasetListApi>

export const patchedDatasetApiNameMax = 400

export const PatchedDatasetApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedDatasetApiNameMax).optional(),
    description: zod.string().nullish(),
    metadata: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
    deleted: zod.boolean().nullish(),
    created_by: UserBasicApi.optional(),
    team: zod.number().optional(),
})

export type PatchedDatasetApi = zod.input<typeof PatchedDatasetApi>
export type PatchedDatasetApiOutput = zod.output<typeof PatchedDatasetApi>

export const evaluationRunRequestApiEventDefault = `$ai_generation`

export const EvaluationRunRequestApi = zod.object({
    evaluation_id: zod.uuid().describe('UUID of the evaluation to run.'),
    target_event_id: zod.uuid().describe('UUID of the $ai_generation event to evaluate.'),
    timestamp: zod.iso
        .datetime({ offset: true })
        .describe('ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup).'),
    event: zod
        .string()
        .default(evaluationRunRequestApiEventDefault)
        .describe("Event name. Defaults to '$ai_generation'."),
    distinct_id: zod.string().nullish().describe('Distinct ID of the event (optional, improves lookup performance).'),
})

export type EvaluationRunRequestApi = zod.input<typeof EvaluationRunRequestApi>
export type EvaluationRunRequestApiOutput = zod.output<typeof EvaluationRunRequestApi>

export const EvaluationStatusEnumApi = zod
    .enum(['active', 'paused', 'error'])
    .describe('\* `active` - Active\n\* `paused` - Paused\n\* `error` - Error')

export type EvaluationStatusEnumApi = zod.input<typeof EvaluationStatusEnumApi>
export type EvaluationStatusEnumApiOutput = zod.output<typeof EvaluationStatusEnumApi>

export const StatusReasonEnumApi = zod
    .enum([
        'provider_key_required',
        'provider_key_deleted',
        'no_default_model',
        'provider_key_invalid',
        'provider_key_permission_denied',
        'provider_key_quota_exceeded',
        'provider_key_rate_limited',
        'model_not_found',
        'hog_error',
    ])
    .describe(
        '\* `provider_key_required` - No provider API key configured\n\* `provider_key_deleted` - Provider API key was deleted\n\* `no_default_model` - No default model available for the selected provider\n\* `provider_key_invalid` - Provider API key is invalid\n\* `provider_key_permission_denied` - Provider API key lacks model access\n\* `provider_key_quota_exceeded` - Provider API key quota exceeded\n\* `provider_key_rate_limited` - Provider API key is rate limited\n\* `model_not_found` - Model not found\n\* `hog_error` - Hog evaluation code failed'
    )

export type StatusReasonEnumApi = zod.input<typeof StatusReasonEnumApi>
export type StatusReasonEnumApiOutput = zod.output<typeof StatusReasonEnumApi>

export const EvaluationTypeEnumApi = zod
    .enum(['llm_judge', 'hog', 'sentiment'])
    .describe('\* `llm_judge` - LLM as a judge\n\* `hog` - Hog\n\* `sentiment` - Sentiment analysis')

export type EvaluationTypeEnumApi = zod.input<typeof EvaluationTypeEnumApi>
export type EvaluationTypeEnumApiOutput = zod.output<typeof EvaluationTypeEnumApi>

export const OutputTypeEnumApi = zod
    .enum(['boolean', 'sentiment'])
    .describe('\* `boolean` - Boolean (Pass\/Fail)\n\* `sentiment` - Sentiment')

export type OutputTypeEnumApi = zod.input<typeof OutputTypeEnumApi>
export type OutputTypeEnumApiOutput = zod.output<typeof OutputTypeEnumApi>

export const evaluationConditionApiIdMax = 100

export const evaluationConditionApiRolloutPercentageDefault = 100
export const evaluationConditionApiRolloutPercentageMin = 0
export const evaluationConditionApiRolloutPercentageMax = 100

export const EvaluationConditionApi = zod
    .object({
        id: zod.string().max(evaluationConditionApiIdMax).describe('Stable identifier for this condition set.'),
        rollout_percentage: zod
            .number()
            .min(evaluationConditionApiRolloutPercentageMin)
            .max(evaluationConditionApiRolloutPercentageMax)
            .default(evaluationConditionApiRolloutPercentageDefault)
            .describe('Percentage (0-100) of matching events to sample for this evaluation. Defaults to 100.'),
        properties: zod
            .array(zod.record(zod.string(), zod.unknown()))
            .optional()
            .describe('Property filters (event or person) that scope which generations match this condition set.'),
    })
    .describe('A trigger condition set controlling which generations an evaluation runs on.')

export type EvaluationConditionApi = zod.input<typeof EvaluationConditionApi>
export type EvaluationConditionApiOutput = zod.output<typeof EvaluationConditionApi>

export const EvaluationTargetEnumApi = zod
    .enum(['generation', 'trace'])
    .describe('\* `generation` - Generation\n\* `trace` - Trace')

export type EvaluationTargetEnumApi = zod.input<typeof EvaluationTargetEnumApi>
export type EvaluationTargetEnumApiOutput = zod.output<typeof EvaluationTargetEnumApi>

export const LLMProviderEnumApi = zod
    .enum([
        'openai',
        'anthropic',
        'gemini',
        'openrouter',
        'fireworks',
        'azure_openai',
        'together_ai',
        'minimax',
        'zeabur',
    ])
    .describe(
        '\* `openai` - Openai\n\* `anthropic` - Anthropic\n\* `gemini` - Gemini\n\* `openrouter` - Openrouter\n\* `fireworks` - Fireworks\n\* `azure_openai` - Azure OpenAI\n\* `together_ai` - Together AI\n\* `minimax` - MiniMax\n\* `zeabur` - Zeabur AI Hub'
    )

export type LLMProviderEnumApi = zod.input<typeof LLMProviderEnumApi>
export type LLMProviderEnumApiOutput = zod.output<typeof LLMProviderEnumApi>

export const modelConfigurationApiModelMax = 100

export const ModelConfigurationApi = zod
    .object({
        provider: LLMProviderEnumApi,
        model: zod.string().max(modelConfigurationApiModelMax),
        provider_key_id: zod
            .uuid()
            .nullish()
            .describe(
                'Optional team provider key to run this evaluation with; it must use the same provider. May be null when no key is pinned or after the selected key is removed.'
            ),
        provider_key_name: zod.string().nullable(),
    })
    .describe('Nested serializer for model configuration.')

export type ModelConfigurationApi = zod.input<typeof ModelConfigurationApi>
export type ModelConfigurationApiOutput = zod.output<typeof ModelConfigurationApi>

export const evaluationApiNameMax = 400

export const evaluationApiEvaluationConfigThreeSourceDefault = `user_messages`
export const evaluationApiOutputConfigAllowsNaDefault = false
export const evaluationApiTargetConfigOneStrategyDefault = `fixed_window`
export const evaluationApiTargetConfigOneWindowSecondsDefault = 1800
export const evaluationApiTargetConfigOneWindowSecondsMin = 10
export const evaluationApiTargetConfigOneWindowSecondsMax = 7200

export const evaluationApiTargetConfigTwoQuietPeriodSecondsDefault = 300
export const evaluationApiTargetConfigTwoQuietPeriodSecondsMin = 10
export const evaluationApiTargetConfigTwoQuietPeriodSecondsMax = 1800

export const evaluationApiTargetConfigTwoMaxAgeSecondsDefault = 7200
export const evaluationApiTargetConfigTwoMaxAgeSecondsMin = 60
export const evaluationApiTargetConfigTwoMaxAgeSecondsMax = 7200

export const EvaluationApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(evaluationApiNameMax).describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    status: EvaluationStatusEnumApi,
    status_reason: zod.union([StatusReasonEnumApi, zod.null()]),
    status_reason_detail: zod
        .string()
        .nullable()
        .describe(
            'Additional detail for the current system-disabled status. This is only populated when the detail is safe to show in the evaluation UI.'
        ),
    evaluation_type: EvaluationTypeEnumApi.describe(
        "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment.\n\n\* `llm_judge` - LLM as a judge\n\* `hog` - Hog\n\* `sentiment` - Sentiment analysis"
    ),
    evaluation_config: zod
        .union([
            zod.object({
                prompt: zod
                    .string()
                    .min(1)
                    .describe('Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.'),
            }),
            zod.object({
                source: zod
                    .string()
                    .min(1)
                    .describe('Hog source code. Must return true (pass), false (fail), or null for N\/A.'),
            }),
            zod.object({
                source: zod
                    .enum(['user_messages'])
                    .default(evaluationApiEvaluationConfigThreeSourceDefault)
                    .describe('Classify sentiment from user messages in the generation input.'),
            }),
        ])
        .optional()
        .describe(
            "Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}."
        ),
    output_type: OutputTypeEnumApi.describe(
        "Output format. Use 'boolean' for pass\/fail evaluations and 'sentiment' for sentiment analysis.\n\n\* `boolean` - Boolean (Pass\/Fail)\n\* `sentiment` - Sentiment"
    ),
    output_config: zod
        .object({
            allows_na: zod
                .boolean()
                .default(evaluationApiOutputConfigAllowsNaDefault)
                .describe('Whether the evaluation can return N\/A for non-applicable generations.'),
        })
        .optional()
        .describe("Output config. For 'boolean' output_type: {allows_na} to permit N\/A results."),
    conditions: zod
        .array(EvaluationConditionApi)
        .optional()
        .describe(
            'Trigger conditions that filter which events are evaluated. OR between condition sets, AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` (0-100, defaults to 100) is the sampling field the dispatcher reads.'
        ),
    target: EvaluationTargetEnumApi.optional().describe(
        "What the evaluation runs on. 'generation' evaluates each matching $ai_generation event individually. 'trace' evaluates the whole trace once: the first matching generation schedules a run that waits for the trace to settle, then evaluates all of its events together. Condition filters still match individual generations — a trace is evaluated when any of its generations matches, and sampling applies per trace. When and how the trace run fires is controlled by target_config's settle strategy.\n\n\* `generation` - Generation\n\* `trace` - Trace"
    ),
    target_config: zod
        .union([
            zod.object({
                strategy: zod
                    .enum(['fixed_window'])
                    .default(evaluationApiTargetConfigOneStrategyDefault)
                    .describe('Wait a fixed window after the first matching generation, then evaluate.'),
                window_seconds: zod
                    .number()
                    .min(evaluationApiTargetConfigOneWindowSecondsMin)
                    .max(evaluationApiTargetConfigOneWindowSecondsMax)
                    .default(evaluationApiTargetConfigOneWindowSecondsDefault)
                    .describe(
                        'Seconds to wait after the first matching generation before evaluating the whole trace. Captured when the run is scheduled — editing it does not change runs already in flight.'
                    ),
            }),
            zod.object({
                strategy: zod
                    .enum(['inactivity'])
                    .describe('Evaluate once the trace has had no new activity for the quiet period.'),
                quiet_period_seconds: zod
                    .number()
                    .min(evaluationApiTargetConfigTwoQuietPeriodSecondsMin)
                    .max(evaluationApiTargetConfigTwoQuietPeriodSecondsMax)
                    .default(evaluationApiTargetConfigTwoQuietPeriodSecondsDefault)
                    .describe('Seconds without new trace activity before the trace counts as settled.'),
                max_age_seconds: zod
                    .number()
                    .min(evaluationApiTargetConfigTwoMaxAgeSecondsMin)
                    .max(evaluationApiTargetConfigTwoMaxAgeSecondsMax)
                    .default(evaluationApiTargetConfigTwoMaxAgeSecondsDefault)
                    .describe(
                        'Hard cap in seconds on the total wait from the first matching generation, even if the trace stays active. Must be at least quiet_period_seconds.'
                    ),
            }),
        ])
        .optional()
        .describe(
            "Target-specific config. For 'trace' target: a settle config discriminated on `strategy` — 'fixed_window' {window_seconds} or 'inactivity' {quiet_period_seconds, max_age_seconds}. Missing strategy means fixed_window. Empty for 'generation'."
        ),
    model_configuration: zod
        .union([ModelConfigurationApi, zod.null()])
        .optional()
        .describe(
            'Provider and model for an llm_judge evaluation. Required when creating or switching to llm_judge. To add or replace a model, provide both provider and model. On an existing configured llm_judge, omit this field to keep the current model; null is rejected. When switching an llm_judge to hog or sentiment, set this field to null. Legacy llm_judge evaluations without a model remain editable without adding one. The nested provider_key_id may be null.'
        ),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

export type EvaluationApi = zod.input<typeof EvaluationApi>
export type EvaluationApiOutput = zod.output<typeof EvaluationApi>

export const PaginatedEvaluationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EvaluationApi),
})

export type PaginatedEvaluationListApi = zod.input<typeof PaginatedEvaluationListApi>
export type PaginatedEvaluationListApiOutput = zod.output<typeof PaginatedEvaluationListApi>

export const patchedEvaluationApiNameMax = 400

export const patchedEvaluationApiEvaluationConfigThreeSourceDefault = `user_messages`
export const patchedEvaluationApiOutputConfigAllowsNaDefault = false
export const patchedEvaluationApiTargetConfigOneStrategyDefault = `fixed_window`
export const patchedEvaluationApiTargetConfigOneWindowSecondsDefault = 1800
export const patchedEvaluationApiTargetConfigOneWindowSecondsMin = 10
export const patchedEvaluationApiTargetConfigOneWindowSecondsMax = 7200

export const patchedEvaluationApiTargetConfigTwoQuietPeriodSecondsDefault = 300
export const patchedEvaluationApiTargetConfigTwoQuietPeriodSecondsMin = 10
export const patchedEvaluationApiTargetConfigTwoQuietPeriodSecondsMax = 1800

export const patchedEvaluationApiTargetConfigTwoMaxAgeSecondsDefault = 7200
export const patchedEvaluationApiTargetConfigTwoMaxAgeSecondsMin = 60
export const patchedEvaluationApiTargetConfigTwoMaxAgeSecondsMax = 7200

export const PatchedEvaluationApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedEvaluationApiNameMax).optional().describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    status: EvaluationStatusEnumApi.optional(),
    status_reason: zod.union([StatusReasonEnumApi, zod.null()]).optional(),
    status_reason_detail: zod
        .string()
        .nullish()
        .describe(
            'Additional detail for the current system-disabled status. This is only populated when the detail is safe to show in the evaluation UI.'
        ),
    evaluation_type: EvaluationTypeEnumApi.optional().describe(
        "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment.\n\n\* `llm_judge` - LLM as a judge\n\* `hog` - Hog\n\* `sentiment` - Sentiment analysis"
    ),
    evaluation_config: zod
        .union([
            zod.object({
                prompt: zod
                    .string()
                    .min(1)
                    .describe('Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.'),
            }),
            zod.object({
                source: zod
                    .string()
                    .min(1)
                    .describe('Hog source code. Must return true (pass), false (fail), or null for N\/A.'),
            }),
            zod.object({
                source: zod
                    .enum(['user_messages'])
                    .default(patchedEvaluationApiEvaluationConfigThreeSourceDefault)
                    .describe('Classify sentiment from user messages in the generation input.'),
            }),
        ])
        .optional()
        .describe(
            "Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}."
        ),
    output_type: OutputTypeEnumApi.optional().describe(
        "Output format. Use 'boolean' for pass\/fail evaluations and 'sentiment' for sentiment analysis.\n\n\* `boolean` - Boolean (Pass\/Fail)\n\* `sentiment` - Sentiment"
    ),
    output_config: zod
        .object({
            allows_na: zod
                .boolean()
                .default(patchedEvaluationApiOutputConfigAllowsNaDefault)
                .describe('Whether the evaluation can return N\/A for non-applicable generations.'),
        })
        .optional()
        .describe("Output config. For 'boolean' output_type: {allows_na} to permit N\/A results."),
    conditions: zod
        .array(EvaluationConditionApi)
        .optional()
        .describe(
            'Trigger conditions that filter which events are evaluated. OR between condition sets, AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` (0-100, defaults to 100) is the sampling field the dispatcher reads.'
        ),
    target: EvaluationTargetEnumApi.optional().describe(
        "What the evaluation runs on. 'generation' evaluates each matching $ai_generation event individually. 'trace' evaluates the whole trace once: the first matching generation schedules a run that waits for the trace to settle, then evaluates all of its events together. Condition filters still match individual generations — a trace is evaluated when any of its generations matches, and sampling applies per trace. When and how the trace run fires is controlled by target_config's settle strategy.\n\n\* `generation` - Generation\n\* `trace` - Trace"
    ),
    target_config: zod
        .union([
            zod.object({
                strategy: zod
                    .enum(['fixed_window'])
                    .default(patchedEvaluationApiTargetConfigOneStrategyDefault)
                    .describe('Wait a fixed window after the first matching generation, then evaluate.'),
                window_seconds: zod
                    .number()
                    .min(patchedEvaluationApiTargetConfigOneWindowSecondsMin)
                    .max(patchedEvaluationApiTargetConfigOneWindowSecondsMax)
                    .default(patchedEvaluationApiTargetConfigOneWindowSecondsDefault)
                    .describe(
                        'Seconds to wait after the first matching generation before evaluating the whole trace. Captured when the run is scheduled — editing it does not change runs already in flight.'
                    ),
            }),
            zod.object({
                strategy: zod
                    .enum(['inactivity'])
                    .describe('Evaluate once the trace has had no new activity for the quiet period.'),
                quiet_period_seconds: zod
                    .number()
                    .min(patchedEvaluationApiTargetConfigTwoQuietPeriodSecondsMin)
                    .max(patchedEvaluationApiTargetConfigTwoQuietPeriodSecondsMax)
                    .default(patchedEvaluationApiTargetConfigTwoQuietPeriodSecondsDefault)
                    .describe('Seconds without new trace activity before the trace counts as settled.'),
                max_age_seconds: zod
                    .number()
                    .min(patchedEvaluationApiTargetConfigTwoMaxAgeSecondsMin)
                    .max(patchedEvaluationApiTargetConfigTwoMaxAgeSecondsMax)
                    .default(patchedEvaluationApiTargetConfigTwoMaxAgeSecondsDefault)
                    .describe(
                        'Hard cap in seconds on the total wait from the first matching generation, even if the trace stays active. Must be at least quiet_period_seconds.'
                    ),
            }),
        ])
        .optional()
        .describe(
            "Target-specific config. For 'trace' target: a settle config discriminated on `strategy` — 'fixed_window' {window_seconds} or 'inactivity' {quiet_period_seconds, max_age_seconds}. Missing strategy means fixed_window. Empty for 'generation'."
        ),
    model_configuration: zod
        .union([ModelConfigurationApi, zod.null()])
        .optional()
        .describe(
            'Provider and model for an llm_judge evaluation. Required when creating or switching to llm_judge. To add or replace a model, provide both provider and model. On an existing configured llm_judge, omit this field to keep the current model; null is rejected. When switching an llm_judge to hog or sentiment, set this field to null. Legacy llm_judge evaluations without a model remain editable without adding one. The nested provider_key_id may be null.'
        ),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

export type PatchedEvaluationApi = zod.input<typeof PatchedEvaluationApi>
export type PatchedEvaluationApiOutput = zod.output<typeof PatchedEvaluationApi>

export const testHogTargetConfigApiWindowSecondsDefault = 1800
export const testHogTargetConfigApiWindowSecondsMin = 10
export const testHogTargetConfigApiWindowSecondsMax = 7200

export const TestHogTargetConfigApi = zod.object({
    window_seconds: zod
        .number()
        .min(testHogTargetConfigApiWindowSecondsMin)
        .max(testHogTargetConfigApiWindowSecondsMax)
        .default(testHogTargetConfigApiWindowSecondsDefault)
        .describe('Aggregation window for trace samples, in seconds.'),
})

export type TestHogTargetConfigApi = zod.input<typeof TestHogTargetConfigApi>
export type TestHogTargetConfigApiOutput = zod.output<typeof TestHogTargetConfigApi>

export const testHogRequestApiSampleCountDefault = 5
export const testHogRequestApiSampleCountMax = 10

export const testHogRequestApiAllowsNaDefault = false
export const testHogRequestApiTargetDefault = `generation`

export const TestHogRequestApi = zod.object({
    source: zod
        .string()
        .min(1)
        .describe('Hog source code to test. Must return a boolean (true = pass, false = fail) or null for N\/A.'),
    sample_count: zod
        .number()
        .min(1)
        .max(testHogRequestApiSampleCountMax)
        .default(testHogRequestApiSampleCountDefault)
        .describe('Number of recent $ai_generation events to test against (1–10, default 5).'),
    allows_na: zod
        .boolean()
        .default(testHogRequestApiAllowsNaDefault)
        .describe('Whether the evaluation can return N\/A for non-applicable generations.'),
    conditions: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe('Optional trigger conditions to filter which events are sampled.'),
    target: EvaluationTargetEnumApi.default(testHogRequestApiTargetDefault).describe(
        "What the evaluation runs against: 'generation' samples individual generations, 'trace' samples whole traces and runs against trace-level globals — matching how the evaluation runs online.\n\n\* `generation` - Generation\n\* `trace` - Trace"
    ),
    target_config: TestHogTargetConfigApi.optional().describe(
        'Target-specific preview settings. For a trace target, set window_seconds between 10 and 7200.'
    ),
})

export type TestHogRequestApi = zod.input<typeof TestHogRequestApi>
export type TestHogRequestApiOutput = zod.output<typeof TestHogRequestApi>

export const TestHogResultItemApi = zod.object({
    sample_id: zod.string().describe('Stable identifier for the sampled generation or trace.'),
    sample_type: EvaluationTargetEnumApi.describe(
        'Type of sampled unit: generation or trace.\n\n\* `generation` - Generation\n\* `trace` - Trace'
    ),
    event_uuid: zod
        .string()
        .nullable()
        .describe('UUID of the sampled $ai_generation event, or null for a trace sample.'),
    trace_id: zod.string().nullable().describe('Trace ID if available.'),
    input_preview: zod.string().describe('First 200 characters of input from the sampled unit.'),
    output_preview: zod.string().describe('First 200 characters of output from the sampled unit.'),
    result: zod.boolean().nullable().describe('True = pass, False = fail, null = N\/A or error.'),
    reasoning: zod.string().nullable().describe('Hog evaluation reasoning string, if any.'),
    error: zod.string().nullable().describe('Error message if the Hog code raised an exception.'),
})

export type TestHogResultItemApi = zod.input<typeof TestHogResultItemApi>
export type TestHogResultItemApiOutput = zod.output<typeof TestHogResultItemApi>

export const TestHogResponseApi = zod.object({
    results: zod.array(TestHogResultItemApi),
    message: zod.string().optional().describe('Optional message, e.g. when no recent events were found.'),
})

export type TestHogResponseApi = zod.input<typeof TestHogResponseApi>
export type TestHogResponseApiOutput = zod.output<typeof TestHogResponseApi>

export const ClusteringConfigApi = zod.object({
    event_filters: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('PostHog property filters that scope automated clustering jobs. Empty array means no saved filters.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type ClusteringConfigApi = zod.input<typeof ClusteringConfigApi>
export type ClusteringConfigApiOutput = zod.output<typeof ClusteringConfigApi>

export const ClusteringConfigSetEventFiltersApi = zod.object({
    event_filters: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'PostHog property filters to save for automated clustering jobs. Pass an empty array to clear filters.'
        ),
})

export type ClusteringConfigSetEventFiltersApi = zod.input<typeof ClusteringConfigSetEventFiltersApi>
export type ClusteringConfigSetEventFiltersApiOutput = zod.output<typeof ClusteringConfigSetEventFiltersApi>

export const AnalysisLevelEnumApi = zod
    .enum(['trace', 'generation', 'evaluation'])
    .describe('\* `trace` - trace\n\* `generation` - generation\n\* `evaluation` - evaluation')

export type AnalysisLevelEnumApi = zod.input<typeof AnalysisLevelEnumApi>
export type AnalysisLevelEnumApiOutput = zod.output<typeof AnalysisLevelEnumApi>

export const clusteringJobApiNameMax = 100

export const ClusteringJobApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(clusteringJobApiNameMax),
    analysis_level: AnalysisLevelEnumApi,
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type ClusteringJobApi = zod.input<typeof ClusteringJobApi>
export type ClusteringJobApiOutput = zod.output<typeof ClusteringJobApi>

export const PaginatedClusteringJobListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ClusteringJobApi),
})

export type PaginatedClusteringJobListApi = zod.input<typeof PaginatedClusteringJobListApi>
export type PaginatedClusteringJobListApiOutput = zod.output<typeof PaginatedClusteringJobListApi>

export const patchedClusteringJobApiNameMax = 100

export const PatchedClusteringJobApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedClusteringJobApiNameMax).optional(),
    analysis_level: AnalysisLevelEnumApi.optional(),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedClusteringJobApi = zod.input<typeof PatchedClusteringJobApi>
export type PatchedClusteringJobApiOutput = zod.output<typeof PatchedClusteringJobApi>

export const EmbeddingNormalizationEnumApi = zod.enum(['none', 'l2']).describe('\* `none` - none\n\* `l2` - l2')

export type EmbeddingNormalizationEnumApi = zod.input<typeof EmbeddingNormalizationEnumApi>
export type EmbeddingNormalizationEnumApiOutput = zod.output<typeof EmbeddingNormalizationEnumApi>

export const DimensionalityReductionMethodEnumApi = zod
    .enum(['none', 'umap', 'pca'])
    .describe('\* `none` - none\n\* `umap` - umap\n\* `pca` - pca')

export type DimensionalityReductionMethodEnumApi = zod.input<typeof DimensionalityReductionMethodEnumApi>
export type DimensionalityReductionMethodEnumApiOutput = zod.output<typeof DimensionalityReductionMethodEnumApi>

export const ClusteringMethodEnumApi = zod
    .enum(['hdbscan', 'kmeans'])
    .describe('\* `hdbscan` - hdbscan\n\* `kmeans` - kmeans')

export type ClusteringMethodEnumApi = zod.input<typeof ClusteringMethodEnumApi>
export type ClusteringMethodEnumApiOutput = zod.output<typeof ClusteringMethodEnumApi>

export const VisualizationMethodEnumApi = zod
    .enum(['umap', 'pca', 'tsne'])
    .describe('\* `umap` - umap\n\* `pca` - pca\n\* `tsne` - tsne')

export type VisualizationMethodEnumApi = zod.input<typeof VisualizationMethodEnumApi>
export type VisualizationMethodEnumApiOutput = zod.output<typeof VisualizationMethodEnumApi>

export const clusteringRunRequestApiLookbackDaysDefault = 7
export const clusteringRunRequestApiLookbackDaysMax = 90

export const clusteringRunRequestApiMaxSamplesDefault = 1500
export const clusteringRunRequestApiMaxSamplesMin = 20
export const clusteringRunRequestApiMaxSamplesMax = 10000

export const clusteringRunRequestApiEmbeddingNormalizationDefault = `none`
export const clusteringRunRequestApiDimensionalityReductionMethodDefault = `umap`
export const clusteringRunRequestApiDimensionalityReductionNdimsDefault = 100
export const clusteringRunRequestApiDimensionalityReductionNdimsMin = 2
export const clusteringRunRequestApiDimensionalityReductionNdimsMax = 500

export const clusteringRunRequestApiClusteringMethodDefault = `hdbscan`
export const clusteringRunRequestApiMinClusterSizeFractionDefault = 0.02
export const clusteringRunRequestApiMinClusterSizeFractionMin = 0.02
export const clusteringRunRequestApiMinClusterSizeFractionMax = 0.5

export const clusteringRunRequestApiHdbscanMinSamplesDefault = 5
export const clusteringRunRequestApiHdbscanMinSamplesMax = 100

export const clusteringRunRequestApiKmeansMinKDefault = 2
export const clusteringRunRequestApiKmeansMinKMin = 2
export const clusteringRunRequestApiKmeansMinKMax = 50

export const clusteringRunRequestApiKmeansMaxKDefault = 20
export const clusteringRunRequestApiKmeansMaxKMin = 2
export const clusteringRunRequestApiKmeansMaxKMax = 100

export const clusteringRunRequestApiRunLabelDefault = ``
export const clusteringRunRequestApiRunLabelMax = 50

export const clusteringRunRequestApiVisualizationMethodDefault = `umap`

export const ClusteringRunRequestApi = zod
    .object({
        lookback_days: zod
            .number()
            .min(1)
            .max(clusteringRunRequestApiLookbackDaysMax)
            .default(clusteringRunRequestApiLookbackDaysDefault)
            .describe('Number of days to look back for traces'),
        max_samples: zod
            .number()
            .min(clusteringRunRequestApiMaxSamplesMin)
            .max(clusteringRunRequestApiMaxSamplesMax)
            .default(clusteringRunRequestApiMaxSamplesDefault)
            .describe('Maximum number of traces to sample for clustering'),
        embedding_normalization: EmbeddingNormalizationEnumApi.default(
            clusteringRunRequestApiEmbeddingNormalizationDefault
        ).describe(
            "Embedding normalization method: 'none' (raw embeddings) or 'l2' (L2 normalize before clustering)\n\n\* `none` - none\n\* `l2` - l2"
        ),
        dimensionality_reduction_method: DimensionalityReductionMethodEnumApi.default(
            clusteringRunRequestApiDimensionalityReductionMethodDefault
        ).describe(
            "Dimensionality reduction method: 'none' (cluster on raw), 'umap', or 'pca'\n\n\* `none` - none\n\* `umap` - umap\n\* `pca` - pca"
        ),
        dimensionality_reduction_ndims: zod
            .number()
            .min(clusteringRunRequestApiDimensionalityReductionNdimsMin)
            .max(clusteringRunRequestApiDimensionalityReductionNdimsMax)
            .default(clusteringRunRequestApiDimensionalityReductionNdimsDefault)
            .describe("Target dimensions for dimensionality reduction (ignored if method is 'none')"),
        clustering_method: ClusteringMethodEnumApi.default(clusteringRunRequestApiClusteringMethodDefault).describe(
            "Clustering algorithm: 'hdbscan' (density-based, auto-determines k) or 'kmeans' (centroid-based)\n\n\* `hdbscan` - hdbscan\n\* `kmeans` - kmeans"
        ),
        min_cluster_size_fraction: zod
            .number()
            .min(clusteringRunRequestApiMinClusterSizeFractionMin)
            .max(clusteringRunRequestApiMinClusterSizeFractionMax)
            .default(clusteringRunRequestApiMinClusterSizeFractionDefault)
            .describe('Minimum cluster size as fraction of total samples (e.g., 0.02 = 2%)'),
        hdbscan_min_samples: zod
            .number()
            .min(1)
            .max(clusteringRunRequestApiHdbscanMinSamplesMax)
            .default(clusteringRunRequestApiHdbscanMinSamplesDefault)
            .describe('HDBSCAN min_samples parameter (higher = more conservative clustering)'),
        kmeans_min_k: zod
            .number()
            .min(clusteringRunRequestApiKmeansMinKMin)
            .max(clusteringRunRequestApiKmeansMinKMax)
            .default(clusteringRunRequestApiKmeansMinKDefault)
            .describe('Minimum number of clusters to try for k-means'),
        kmeans_max_k: zod
            .number()
            .min(clusteringRunRequestApiKmeansMaxKMin)
            .max(clusteringRunRequestApiKmeansMaxKMax)
            .default(clusteringRunRequestApiKmeansMaxKDefault)
            .describe('Maximum number of clusters to try for k-means'),
        run_label: zod
            .string()
            .max(clusteringRunRequestApiRunLabelMax)
            .default(clusteringRunRequestApiRunLabelDefault)
            .describe('Optional label\/tag for the clustering run (used as suffix in run_id for tracking experiments)'),
        visualization_method: VisualizationMethodEnumApi.default(
            clusteringRunRequestApiVisualizationMethodDefault
        ).describe(
            "Method for 2D scatter plot visualization: 'umap', 'pca', or 'tsne'\n\n\* `umap` - umap\n\* `pca` - pca\n\* `tsne` - tsne"
        ),
        event_filters: zod
            .array(zod.record(zod.string(), zod.unknown()))
            .optional()
            .describe('Property filters to scope which traces are included in clustering (PostHog standard format)'),
        clustering_job_id: zod
            .uuid()
            .nullish()
            .describe(
                "If provided, use this clustering job's analysis_level and event_filters instead of request params"
            ),
    })
    .describe('Serializer for clustering workflow request parameters.')

export type ClusteringRunRequestApi = zod.input<typeof ClusteringRunRequestApi>
export type ClusteringRunRequestApiOutput = zod.output<typeof ClusteringRunRequestApi>

export const LLMProviderKeyStateEnumApi = zod
    .enum(['unknown', 'ok', 'invalid', 'error'])
    .describe('\* `unknown` - Unknown\n\* `ok` - Ok\n\* `invalid` - Invalid\n\* `error` - Error')

export type LLMProviderKeyStateEnumApi = zod.input<typeof LLMProviderKeyStateEnumApi>
export type LLMProviderKeyStateEnumApiOutput = zod.output<typeof LLMProviderKeyStateEnumApi>

export const lLMProviderKeyApiNameMax = 255

export const lLMProviderKeyApiApiVersionMax = 20

export const lLMProviderKeyApiSetAsActiveDefault = false

export const LLMProviderKeyApi = zod.object({
    id: zod.uuid(),
    provider: LLMProviderEnumApi,
    name: zod.string().max(lLMProviderKeyApiNameMax),
    state: LLMProviderKeyStateEnumApi,
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    azure_endpoint: zod.url().optional().describe('Azure OpenAI endpoint URL'),
    api_version: zod.string().max(lLMProviderKeyApiApiVersionMax).optional().describe('Azure OpenAI API version'),
    azure_endpoint_display: zod.string().nullable().describe('Azure endpoint (read-only, for display)'),
    api_version_display: zod.string().nullable().describe('Azure API version (read-only, for display)'),
    set_as_active: zod.boolean().default(lLMProviderKeyApiSetAsActiveDefault),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    last_used_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type LLMProviderKeyApi = zod.input<typeof LLMProviderKeyApi>
export type LLMProviderKeyApiOutput = zod.output<typeof LLMProviderKeyApi>

export const EvaluationConfigApi = zod.object({
    active_provider_key: zod
        .union([LLMProviderKeyApi, zod.null()])
        .describe('Provider key used to run llm_judge evals; null if none configured yet.'),
    created_at: zod.iso.datetime({ offset: true }).describe('Timestamp when the evaluation config row was created.'),
    updated_at: zod.iso
        .datetime({ offset: true })
        .describe('Timestamp when the evaluation config row was last modified.'),
})

export type EvaluationConfigApi = zod.input<typeof EvaluationConfigApi>
export type EvaluationConfigApiOutput = zod.output<typeof EvaluationConfigApi>

export const EvaluationConfigSetActiveKeyRequestApi = zod.object({
    key_id: zod
        .uuid()
        .describe(
            "UUID of an existing LLM provider key (state must be 'ok') to mark as the active key for running llm_judge evaluations team-wide."
        ),
})

export type EvaluationConfigSetActiveKeyRequestApi = zod.input<typeof EvaluationConfigSetActiveKeyRequestApi>
export type EvaluationConfigSetActiveKeyRequestApiOutput = zod.output<typeof EvaluationConfigSetActiveKeyRequestApi>

export const EvaluationReportFrequencyEnumApi = zod
    .enum(['scheduled', 'every_n'])
    .describe('\* `scheduled` - Scheduled\n\* `every_n` - Every N')

export type EvaluationReportFrequencyEnumApi = zod.input<typeof EvaluationReportFrequencyEnumApi>
export type EvaluationReportFrequencyEnumApiOutput = zod.output<typeof EvaluationReportFrequencyEnumApi>

export const evaluationReportApiMaxSampleSizeMin = -2147483648
export const evaluationReportApiMaxSampleSizeMax = 2147483647

export const evaluationReportApiTriggerThresholdMin = 100
export const evaluationReportApiTriggerThresholdMax = 10000

export const evaluationReportApiCooldownMinutesMin = 60
export const evaluationReportApiCooldownMinutesMax = 1440

export const evaluationReportApiDailyRunCapMax = 24

export const EvaluationReportApi = zod.object({
    id: zod.uuid(),
    evaluation: zod.uuid().describe('UUID of the evaluation this report config belongs to.'),
    frequency: EvaluationReportFrequencyEnumApi.optional().describe(
        "How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule.\n\n\* `scheduled` - Scheduled\n\* `every_n` - Every N"
    ),
    rrule: zod
        .string()
        .optional()
        .describe(
            "RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    starts_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe(
            'Read-only anchor datetime used to expand scheduled reports. The server sets this automatically when a report is switched to scheduled mode.'
        ),
    timezone_name: zod.string().describe('Read-only timezone used for scheduled reports. Evaluation reports use UTC.'),
    next_delivery_date: zod.iso.datetime({ offset: true }).nullable(),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team."
        ),
    max_sample_size: zod
        .number()
        .min(evaluationReportApiMaxSampleSizeMin)
        .max(evaluationReportApiMaxSampleSizeMax)
        .optional()
        .describe('Maximum number of evaluation runs included in each report. Defaults to 200.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active. Disabled configs do not fire.'),
    deleted: zod
        .boolean()
        .describe(
            'Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use enabled=false to stop deliveries.'
        ),
    last_delivered_at: zod.iso.datetime({ offset: true }).nullable(),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe(
            'Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt.'
        ),
    trigger_threshold: zod
        .number()
        .min(evaluationReportApiTriggerThresholdMin)
        .max(evaluationReportApiTriggerThresholdMax)
        .nullish()
        .describe(
            "Number of new evaluation results that triggers a report (every_n mode only). Min 100, max 10000. Defaults to 100. Required when frequency is 'every_n'."
        ),
    cooldown_minutes: zod
        .number()
        .min(evaluationReportApiCooldownMinutesMin)
        .max(evaluationReportApiCooldownMinutesMax)
        .optional()
        .describe(
            'Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.'
        ),
    daily_run_cap: zod
        .number()
        .min(1)
        .max(evaluationReportApiDailyRunCapMax)
        .optional()
        .describe(
            'Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.'
        ),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type EvaluationReportApi = zod.input<typeof EvaluationReportApi>
export type EvaluationReportApiOutput = zod.output<typeof EvaluationReportApi>

export const PaginatedEvaluationReportListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EvaluationReportApi),
})

export type PaginatedEvaluationReportListApi = zod.input<typeof PaginatedEvaluationReportListApi>
export type PaginatedEvaluationReportListApiOutput = zod.output<typeof PaginatedEvaluationReportListApi>

export const evaluationReportUpdateApiMaxSampleSizeMin = -2147483648
export const evaluationReportUpdateApiMaxSampleSizeMax = 2147483647

export const evaluationReportUpdateApiTriggerThresholdMin = 100
export const evaluationReportUpdateApiTriggerThresholdMax = 10000

export const evaluationReportUpdateApiCooldownMinutesMin = 60
export const evaluationReportUpdateApiCooldownMinutesMax = 1440

export const evaluationReportUpdateApiDailyRunCapMax = 24

export const EvaluationReportUpdateApi = zod.object({
    id: zod.uuid(),
    evaluation: zod.uuid().describe('UUID of the evaluation this report config belongs to.'),
    frequency: EvaluationReportFrequencyEnumApi.optional().describe(
        "How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule.\n\n\* `scheduled` - Scheduled\n\* `every_n` - Every N"
    ),
    rrule: zod
        .string()
        .optional()
        .describe(
            "RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    starts_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe(
            'Read-only anchor datetime used to expand scheduled reports. The server sets this automatically when a report is switched to scheduled mode.'
        ),
    timezone_name: zod.string().describe('Read-only timezone used for scheduled reports. Evaluation reports use UTC.'),
    next_delivery_date: zod.iso.datetime({ offset: true }).nullable(),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team."
        ),
    max_sample_size: zod
        .number()
        .min(evaluationReportUpdateApiMaxSampleSizeMin)
        .max(evaluationReportUpdateApiMaxSampleSizeMax)
        .optional()
        .describe('Maximum number of evaluation runs included in each report. Defaults to 200.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active. Disabled configs do not fire.'),
    deleted: zod
        .boolean()
        .describe(
            'Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use enabled=false to stop deliveries.'
        ),
    last_delivered_at: zod.iso.datetime({ offset: true }).nullable(),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe(
            'Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt.'
        ),
    trigger_threshold: zod
        .number()
        .min(evaluationReportUpdateApiTriggerThresholdMin)
        .max(evaluationReportUpdateApiTriggerThresholdMax)
        .nullish()
        .describe(
            "Number of new evaluation results that triggers a report (every_n mode only). Min 100, max 10000. Defaults to 100. Required when frequency is 'every_n'."
        ),
    cooldown_minutes: zod
        .number()
        .min(evaluationReportUpdateApiCooldownMinutesMin)
        .max(evaluationReportUpdateApiCooldownMinutesMax)
        .optional()
        .describe(
            'Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.'
        ),
    daily_run_cap: zod
        .number()
        .min(1)
        .max(evaluationReportUpdateApiDailyRunCapMax)
        .optional()
        .describe(
            'Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.'
        ),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type EvaluationReportUpdateApi = zod.input<typeof EvaluationReportUpdateApi>
export type EvaluationReportUpdateApiOutput = zod.output<typeof EvaluationReportUpdateApi>

export const patchedEvaluationReportUpdateApiMaxSampleSizeMin = -2147483648
export const patchedEvaluationReportUpdateApiMaxSampleSizeMax = 2147483647

export const patchedEvaluationReportUpdateApiTriggerThresholdMin = 100
export const patchedEvaluationReportUpdateApiTriggerThresholdMax = 10000

export const patchedEvaluationReportUpdateApiCooldownMinutesMin = 60
export const patchedEvaluationReportUpdateApiCooldownMinutesMax = 1440

export const patchedEvaluationReportUpdateApiDailyRunCapMax = 24

export const PatchedEvaluationReportUpdateApi = zod.object({
    id: zod.uuid().optional(),
    evaluation: zod.uuid().optional().describe('UUID of the evaluation this report config belongs to.'),
    frequency: EvaluationReportFrequencyEnumApi.optional().describe(
        "How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule.\n\n\* `scheduled` - Scheduled\n\* `every_n` - Every N"
    ),
    rrule: zod
        .string()
        .optional()
        .describe(
            "RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    starts_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'Read-only anchor datetime used to expand scheduled reports. The server sets this automatically when a report is switched to scheduled mode.'
        ),
    timezone_name: zod
        .string()
        .optional()
        .describe('Read-only timezone used for scheduled reports. Evaluation reports use UTC.'),
    next_delivery_date: zod.iso.datetime({ offset: true }).nullish(),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team."
        ),
    max_sample_size: zod
        .number()
        .min(patchedEvaluationReportUpdateApiMaxSampleSizeMin)
        .max(patchedEvaluationReportUpdateApiMaxSampleSizeMax)
        .optional()
        .describe('Maximum number of evaluation runs included in each report. Defaults to 200.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active. Disabled configs do not fire.'),
    deleted: zod
        .boolean()
        .optional()
        .describe(
            'Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use enabled=false to stop deliveries.'
        ),
    last_delivered_at: zod.iso.datetime({ offset: true }).nullish(),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe(
            'Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt.'
        ),
    trigger_threshold: zod
        .number()
        .min(patchedEvaluationReportUpdateApiTriggerThresholdMin)
        .max(patchedEvaluationReportUpdateApiTriggerThresholdMax)
        .nullish()
        .describe(
            "Number of new evaluation results that triggers a report (every_n mode only). Min 100, max 10000. Defaults to 100. Required when frequency is 'every_n'."
        ),
    cooldown_minutes: zod
        .number()
        .min(patchedEvaluationReportUpdateApiCooldownMinutesMin)
        .max(patchedEvaluationReportUpdateApiCooldownMinutesMax)
        .optional()
        .describe(
            'Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.'
        ),
    daily_run_cap: zod
        .number()
        .min(1)
        .max(patchedEvaluationReportUpdateApiDailyRunCapMax)
        .optional()
        .describe(
            'Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.'
        ),
    created_by: zod.number().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedEvaluationReportUpdateApi = zod.input<typeof PatchedEvaluationReportUpdateApi>
export type PatchedEvaluationReportUpdateApiOutput = zod.output<typeof PatchedEvaluationReportUpdateApi>

export const EvaluationReportSectionApi = zod.object({
    title: zod.string().optional().describe('Agent-generated section heading.'),
    content: zod.string().optional().describe('Markdown narrative for this section.'),
})

export type EvaluationReportSectionApi = zod.input<typeof EvaluationReportSectionApi>
export type EvaluationReportSectionApiOutput = zod.output<typeof EvaluationReportSectionApi>

export const EvaluationReportCitationApi = zod.object({
    generation_id: zod.string().optional().describe('Optional generation UUID for generation-target report citations.'),
    trace_id: zod.string().optional().describe('Identifier of the trace cited by this report.'),
    reason: zod.string().optional().describe('Short explanation of why this example is cited.'),
})

export type EvaluationReportCitationApi = zod.input<typeof EvaluationReportCitationApi>
export type EvaluationReportCitationApiOutput = zod.output<typeof EvaluationReportCitationApi>

export const GenerationStatusEnumApi = zod
    .enum(['completed', 'metrics_unavailable'])
    .describe('\* `completed` - completed\n\* `metrics_unavailable` - metrics_unavailable')

export type GenerationStatusEnumApi = zod.input<typeof GenerationStatusEnumApi>
export type GenerationStatusEnumApiOutput = zod.output<typeof GenerationStatusEnumApi>

export const EvaluationReportMetricsApi = zod.object({
    output_type: OutputTypeEnumApi.optional().describe(
        'Evaluation result type. Stored metrics without this field represent boolean evaluations.\n\n\* `boolean` - Boolean (Pass\/Fail)\n\* `sentiment` - Sentiment'
    ),
    total_runs: zod.number().optional().describe('Number of evaluation results in the report period.'),
    result_counts: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Count by output-specific result label, such as pass\/fail\/N\/A or positive\/neutral\/negative.'),
    result_rates: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Percentage by output-specific result label, from 0 to 100.'),
    period_start: zod
        .string()
        .optional()
        .describe('ISO 8601 start of the evaluation window represented by these metrics.'),
    period_end: zod.string().optional().describe('ISO 8601 end of the evaluation window represented by these metrics.'),
    previous_total_runs: zod
        .number()
        .nullish()
        .describe('Number of evaluation results in the previous comparison period, or null when unavailable.'),
    previous_result_counts: zod
        .record(zod.string(), zod.number())
        .nullish()
        .describe('Count by result label for the previous period, or null when unavailable.'),
    previous_result_rates: zod
        .record(zod.string(), zod.number())
        .nullish()
        .describe('Percentage by result label for the previous period, or null when unavailable.'),
    pass_rate: zod.number().optional().describe('Boolean pass percentage, excluding results marked not applicable.'),
    previous_pass_rate: zod
        .number()
        .nullish()
        .describe('Boolean pass percentage for the previous period, or null when unavailable.'),
})

export type EvaluationReportMetricsApi = zod.input<typeof EvaluationReportMetricsApi>
export type EvaluationReportMetricsApiOutput = zod.output<typeof EvaluationReportMetricsApi>

export const EvaluationReportRunContentApi = zod.object({
    evaluation_target: EvaluationTargetEnumApi.optional().describe(
        'Evaluation target analyzed by this report run. Legacy runs without this field targeted generations.\n\n\* `generation` - Generation\n\* `trace` - Trace'
    ),
    title: zod.string().optional().describe('Agent-generated report headline.'),
    sections: zod.array(EvaluationReportSectionApi).optional().describe('Ordered narrative sections in the report.'),
    citations: zod
        .array(EvaluationReportCitationApi)
        .optional()
        .describe('References grounding findings in the report.'),
    generation_status: GenerationStatusEnumApi.optional().describe(
        'Whether report generation completed or metrics were temporarily unavailable. Legacy runs without this field completed normally.\n\n\* `completed` - completed\n\* `metrics_unavailable` - metrics_unavailable'
    ),
    metrics: zod
        .union([EvaluationReportMetricsApi, zod.null()])
        .optional()
        .describe('Structured metrics for completed reports, or null when metrics were temporarily unavailable.'),
})

export type EvaluationReportRunContentApi = zod.input<typeof EvaluationReportRunContentApi>
export type EvaluationReportRunContentApiOutput = zod.output<typeof EvaluationReportRunContentApi>

export const DeliveryStatusEnumApi = zod
    .enum(['pending', 'generated', 'delivered', 'partial_failure', 'failed'])
    .describe(
        '\* `pending` - Pending\n\* `generated` - Generated\n\* `delivered` - Delivered\n\* `partial_failure` - Partial Failure\n\* `failed` - Failed'
    )

export type DeliveryStatusEnumApi = zod.input<typeof DeliveryStatusEnumApi>
export type DeliveryStatusEnumApiOutput = zod.output<typeof DeliveryStatusEnumApi>

export const EvaluationReportRunApi = zod.object({
    id: zod.uuid().describe('UUID of this report run.'),
    report: zod.uuid().describe('UUID of the report config that generated this run.'),
    content: EvaluationReportRunContentApi.describe(
        'Structured report narrative, citations, and metrics. Legacy runs may contain only some fields.'
    ),
    metadata: zod
        .union([EvaluationReportMetricsApi, zod.null()])
        .describe('Legacy mirror of content.metrics. May contain partial boolean metrics on older runs.'),
    period_start: zod.iso.datetime({ offset: true }).describe('Start of the evaluation window covered by this report.'),
    period_end: zod.iso.datetime({ offset: true }).describe('End of the evaluation window covered by this report.'),
    delivery_status: DeliveryStatusEnumApi.describe(
        "Delivery result: 'pending', 'generated', 'delivered', 'partial_failure', or 'failed'.\n\n\* `pending` - Pending\n\* `generated` - Generated\n\* `delivered` - Delivered\n\* `partial_failure` - Partial Failure\n\* `failed` - Failed"
    ),
    delivery_errors: zod
        .array(zod.string())
        .describe('Delivery error messages. Empty when all configured deliveries succeeded.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this report run was created.'),
})

export type EvaluationReportRunApi = zod.input<typeof EvaluationReportRunApi>
export type EvaluationReportRunApiOutput = zod.output<typeof EvaluationReportRunApi>

export const PaginatedEvaluationReportRunListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EvaluationReportRunApi),
})

export type PaginatedEvaluationReportRunListApi = zod.input<typeof PaginatedEvaluationReportRunListApi>
export type PaginatedEvaluationReportRunListApiOutput = zod.output<typeof PaginatedEvaluationReportRunListApi>

export const FilterEnumApi = zod
    .enum(['all', 'pass', 'fail', 'na'])
    .describe('\* `all` - all\n\* `pass` - pass\n\* `fail` - fail\n\* `na` - na')

export type FilterEnumApi = zod.input<typeof FilterEnumApi>
export type FilterEnumApiOutput = zod.output<typeof FilterEnumApi>

export const evaluationSummaryRequestApiFilterDefault = `all`
export const evaluationSummaryRequestApiGenerationIdsMax = 250

export const evaluationSummaryRequestApiForceRefreshDefault = false

export const EvaluationSummaryRequestApi = zod
    .object({
        evaluation_id: zod.uuid().describe('UUID of the evaluation config to summarize'),
        filter: FilterEnumApi.default(evaluationSummaryRequestApiFilterDefault).describe(
            "Filter type to apply ('all', 'pass', 'fail', or 'na')\n\n\* `all` - all\n\* `pass` - pass\n\* `fail` - fail\n\* `na` - na"
        ),
        generation_ids: zod
            .array(zod.uuid())
            .max(evaluationSummaryRequestApiGenerationIdsMax)
            .optional()
            .describe('Optional: specific generation IDs to include in summary (max 250)'),
        force_refresh: zod
            .boolean()
            .default(evaluationSummaryRequestApiForceRefreshDefault)
            .describe('If true, bypass cache and generate a fresh summary'),
    })
    .describe('Request serializer for evaluation summary - accepts IDs only, fetches data server-side.')

export type EvaluationSummaryRequestApi = zod.input<typeof EvaluationSummaryRequestApi>
export type EvaluationSummaryRequestApiOutput = zod.output<typeof EvaluationSummaryRequestApi>

export const EvaluationPatternApi = zod.object({
    title: zod.string(),
    description: zod.string(),
    frequency: zod.string(),
    example_generation_ids: zod.array(zod.string()),
})

export type EvaluationPatternApi = zod.input<typeof EvaluationPatternApi>
export type EvaluationPatternApiOutput = zod.output<typeof EvaluationPatternApi>

export const EvaluationSummaryStatisticsApi = zod.object({
    total_analyzed: zod.number(),
    pass_count: zod.number(),
    fail_count: zod.number(),
    na_count: zod.number(),
})

export type EvaluationSummaryStatisticsApi = zod.input<typeof EvaluationSummaryStatisticsApi>
export type EvaluationSummaryStatisticsApiOutput = zod.output<typeof EvaluationSummaryStatisticsApi>

export const EvaluationSummaryResponseApi = zod.object({
    overall_assessment: zod.string(),
    pass_patterns: zod.array(EvaluationPatternApi),
    fail_patterns: zod.array(EvaluationPatternApi),
    na_patterns: zod.array(EvaluationPatternApi),
    recommendations: zod.array(zod.string()),
    statistics: EvaluationSummaryStatisticsApi,
})

export type EvaluationSummaryResponseApi = zod.input<typeof EvaluationSummaryResponseApi>
export type EvaluationSummaryResponseApiOutput = zod.output<typeof EvaluationSummaryResponseApi>

export const EvaluationSummaryThrottleResponseApi = zod.object({
    type: zod.string().describe('Error category'),
    code: zod.string().describe('Machine-readable error code'),
    detail: zod.string().describe('Why the request was throttled'),
    attr: zod.string().nullable().describe('Related request field, when applicable'),
})

export type EvaluationSummaryThrottleResponseApi = zod.input<typeof EvaluationSummaryThrottleResponseApi>
export type EvaluationSummaryThrottleResponseApiOutput = zod.output<typeof EvaluationSummaryThrottleResponseApi>

export const LLMModelInfoApi = zod.object({
    id: zod.string().describe("Provider-specific model identifier (e.g. 'gpt-4o-mini', 'claude-3-5-sonnet-20241022')."),
})

export type LLMModelInfoApi = zod.input<typeof LLMModelInfoApi>
export type LLMModelInfoApiOutput = zod.output<typeof LLMModelInfoApi>

export const LLMModelsListResponseApi = zod.object({
    models: zod.array(LLMModelInfoApi).describe('Models supported for the requested provider.'),
})

export type LLMModelsListResponseApi = zod.input<typeof LLMModelsListResponseApi>
export type LLMModelsListResponseApiOutput = zod.output<typeof LLMModelsListResponseApi>

export const OfflineExperimentItemsRequestApi = zod.object({
    experiment_id: zod.string().describe('`$ai_experiment_id` whose offline-evaluation items to return.'),
    date_from: zod
        .string()
        .nullish()
        .describe('Lower bound on `timestamp` (ISO-8601). Omit to leave the lower bound open.'),
    date_to: zod
        .string()
        .nullish()
        .describe('Upper bound on `timestamp` (ISO-8601). Omit to leave the upper bound open.'),
})

export type OfflineExperimentItemsRequestApi = zod.input<typeof OfflineExperimentItemsRequestApi>
export type OfflineExperimentItemsRequestApiOutput = zod.output<typeof OfflineExperimentItemsRequestApi>

export const OfflineExperimentItemsResponseApi = zod.object({
    results: zod
        .array(zod.array(zod.unknown()))
        .describe('Tuple-positional rows; positions match `RawOfflineExperimentMetricRow` in the frontend.'),
})

export type OfflineExperimentItemsResponseApi = zod.input<typeof OfflineExperimentItemsResponseApi>
export type OfflineExperimentItemsResponseApiOutput = zod.output<typeof OfflineExperimentItemsResponseApi>

export const parserRecipeApiNameMax = 255

export const parserRecipeApiSourceMax = 100000

export const ParserRecipeApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(parserRecipeApiNameMax).describe('Human-readable recipe name shown in the editor.'),
    source: zod
        .string()
        .max(parserRecipeApiSourceMax)
        .describe(
            'Raw YAML recipe source. Must parse as YAML; recipe semantics are compiled and validated client-side.'
        ),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the recipe.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type ParserRecipeApi = zod.input<typeof ParserRecipeApi>
export type ParserRecipeApiOutput = zod.output<typeof ParserRecipeApi>

export const PaginatedParserRecipeListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ParserRecipeApi),
})

export type PaginatedParserRecipeListApi = zod.input<typeof PaginatedParserRecipeListApi>
export type PaginatedParserRecipeListApiOutput = zod.output<typeof PaginatedParserRecipeListApi>

export const patchedParserRecipeApiNameMax = 255

export const patchedParserRecipeApiSourceMax = 100000

export const PatchedParserRecipeApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedParserRecipeApiNameMax)
        .optional()
        .describe('Human-readable recipe name shown in the editor.'),
    source: zod
        .string()
        .max(patchedParserRecipeApiSourceMax)
        .optional()
        .describe(
            'Raw YAML recipe source. Must parse as YAML; recipe semantics are compiled and validated client-side.'
        ),
    created_by: zod.union([UserBasicApi, zod.null()]).optional().describe('User who created the recipe.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedParserRecipeApi = zod.input<typeof PatchedParserRecipeApi>
export type PatchedParserRecipeApiOutput = zod.output<typeof PatchedParserRecipeApi>

export const PaginatedLLMProviderKeyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LLMProviderKeyApi),
})

export type PaginatedLLMProviderKeyListApi = zod.input<typeof PaginatedLLMProviderKeyListApi>
export type PaginatedLLMProviderKeyListApiOutput = zod.output<typeof PaginatedLLMProviderKeyListApi>

export const patchedLLMProviderKeyApiNameMax = 255

export const patchedLLMProviderKeyApiApiVersionMax = 20

export const patchedLLMProviderKeyApiSetAsActiveDefault = false

export const PatchedLLMProviderKeyApi = zod.object({
    id: zod.uuid().optional(),
    provider: LLMProviderEnumApi.optional(),
    name: zod.string().max(patchedLLMProviderKeyApiNameMax).optional(),
    state: LLMProviderKeyStateEnumApi.optional(),
    error_message: zod.string().nullish(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string().optional(),
    azure_endpoint: zod.url().optional().describe('Azure OpenAI endpoint URL'),
    api_version: zod
        .string()
        .max(patchedLLMProviderKeyApiApiVersionMax)
        .optional()
        .describe('Azure OpenAI API version'),
    azure_endpoint_display: zod.string().nullish().describe('Azure endpoint (read-only, for display)'),
    api_version_display: zod.string().nullish().describe('Azure API version (read-only, for display)'),
    set_as_active: zod.boolean().default(patchedLLMProviderKeyApiSetAsActiveDefault),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    last_used_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedLLMProviderKeyApi = zod.input<typeof PatchedLLMProviderKeyApi>
export type PatchedLLMProviderKeyApiOutput = zod.output<typeof PatchedLLMProviderKeyApi>

export const ReviewQueueItemApi = zod.object({
    id: zod.uuid(),
    queue_id: zod.uuid().describe('Review queue ID that currently owns this pending trace.'),
    queue_name: zod.string().describe('Human-readable name of the queue that currently owns this pending trace.'),
    trace_id: zod.string().describe('Trace ID currently pending review.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi.describe('User who queued this trace.'),
    team: zod.number(),
})

export type ReviewQueueItemApi = zod.input<typeof ReviewQueueItemApi>
export type ReviewQueueItemApiOutput = zod.output<typeof ReviewQueueItemApi>

export const PaginatedReviewQueueItemListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReviewQueueItemApi),
})

export type PaginatedReviewQueueItemListApi = zod.input<typeof PaginatedReviewQueueItemListApi>
export type PaginatedReviewQueueItemListApiOutput = zod.output<typeof PaginatedReviewQueueItemListApi>

export const reviewQueueItemCreateApiTraceIdMax = 255

export const ReviewQueueItemCreateApi = zod.object({
    queue_id: zod.uuid().describe('Review queue ID that should own this pending trace.'),
    trace_id: zod
        .string()
        .max(reviewQueueItemCreateApiTraceIdMax)
        .describe('Trace ID to add to the selected review queue.'),
})

export type ReviewQueueItemCreateApi = zod.input<typeof ReviewQueueItemCreateApi>
export type ReviewQueueItemCreateApiOutput = zod.output<typeof ReviewQueueItemCreateApi>

export const PatchedReviewQueueItemUpdateApi = zod.object({
    queue_id: zod.uuid().optional().describe('Review queue ID that should own this pending trace.'),
})

export type PatchedReviewQueueItemUpdateApi = zod.input<typeof PatchedReviewQueueItemUpdateApi>
export type PatchedReviewQueueItemUpdateApiOutput = zod.output<typeof PatchedReviewQueueItemUpdateApi>

export const ReviewQueueApi = zod.object({
    id: zod.uuid(),
    name: zod.string().describe('Human-readable queue name.'),
    pending_item_count: zod.number().describe('Number of pending traces currently assigned to this queue.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi.describe('User who created this review queue.'),
    team: zod.number(),
})

export type ReviewQueueApi = zod.input<typeof ReviewQueueApi>
export type ReviewQueueApiOutput = zod.output<typeof ReviewQueueApi>

export const PaginatedReviewQueueListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReviewQueueApi),
})

export type PaginatedReviewQueueListApi = zod.input<typeof PaginatedReviewQueueListApi>
export type PaginatedReviewQueueListApiOutput = zod.output<typeof PaginatedReviewQueueListApi>

export const reviewQueueCreateApiNameMax = 255

export const ReviewQueueCreateApi = zod.object({
    name: zod.string().max(reviewQueueCreateApiNameMax).describe('Human-readable queue name.'),
})

export type ReviewQueueCreateApi = zod.input<typeof ReviewQueueCreateApi>
export type ReviewQueueCreateApiOutput = zod.output<typeof ReviewQueueCreateApi>

export const patchedReviewQueueUpdateApiNameMax = 255

export const PatchedReviewQueueUpdateApi = zod.object({
    name: zod.string().max(patchedReviewQueueUpdateApiNameMax).optional().describe('Human-readable queue name.'),
})

export type PatchedReviewQueueUpdateApi = zod.input<typeof PatchedReviewQueueUpdateApi>
export type PatchedReviewQueueUpdateApiOutput = zod.output<typeof PatchedReviewQueueUpdateApi>

export const ExperimentMetricKindEnumApi = zod
    .enum(['categorical', 'numeric', 'boolean'])
    .describe('\* `categorical` - categorical\n\* `numeric` - numeric\n\* `boolean` - boolean')

export type ExperimentMetricKindEnumApi = zod.input<typeof ExperimentMetricKindEnumApi>
export type ExperimentMetricKindEnumApiOutput = zod.output<typeof ExperimentMetricKindEnumApi>

export const categoricalScoreOptionApiKeyMax = 128

export const categoricalScoreOptionApiLabelMax = 256

export const CategoricalScoreOptionApi = zod.object({
    key: zod
        .string()
        .max(categoricalScoreOptionApiKeyMax)
        .describe('Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'),
    label: zod.string().max(categoricalScoreOptionApiLabelMax).describe('Human-readable option label.'),
})

export type CategoricalScoreOptionApi = zod.input<typeof CategoricalScoreOptionApi>
export type CategoricalScoreOptionApiOutput = zod.output<typeof CategoricalScoreOptionApi>

export const SelectionModeEnumApi = zod
    .enum(['single', 'multiple'])
    .describe('\* `single` - single\n\* `multiple` - multiple')

export type SelectionModeEnumApi = zod.input<typeof SelectionModeEnumApi>
export type SelectionModeEnumApiOutput = zod.output<typeof SelectionModeEnumApi>

export const CategoricalScoreDefinitionConfigApi = zod.object({
    options: zod.array(CategoricalScoreOptionApi).describe('Ordered categorical options available to the scorer.'),
    selection_mode: SelectionModeEnumApi.optional().describe(
        'Whether reviewers can select one option or multiple options. Defaults to `single`.\n\n\* `single` - single\n\* `multiple` - multiple'
    ),
    min_selections: zod
        .number()
        .min(1)
        .nullish()
        .describe('Optional minimum number of options that can be selected when `selection_mode` is `multiple`.'),
    max_selections: zod
        .number()
        .min(1)
        .nullish()
        .describe('Optional maximum number of options that can be selected when `selection_mode` is `multiple`.'),
})

export type CategoricalScoreDefinitionConfigApi = zod.input<typeof CategoricalScoreDefinitionConfigApi>
export type CategoricalScoreDefinitionConfigApiOutput = zod.output<typeof CategoricalScoreDefinitionConfigApi>

export const NumericScoreDefinitionConfigApi = zod.object({
    min: zod.number().nullish().describe('Optional inclusive minimum score.'),
    max: zod.number().nullish().describe('Optional inclusive maximum score.'),
    step: zod.number().nullish().describe('Optional increment step for numeric input, for example 1 or 0.5.'),
})

export type NumericScoreDefinitionConfigApi = zod.input<typeof NumericScoreDefinitionConfigApi>
export type NumericScoreDefinitionConfigApiOutput = zod.output<typeof NumericScoreDefinitionConfigApi>

export const BooleanScoreDefinitionConfigApi = zod.object({
    true_label: zod.string().optional().describe('Optional label for a true value.'),
    false_label: zod.string().optional().describe('Optional label for a false value.'),
})

export type BooleanScoreDefinitionConfigApi = zod.input<typeof BooleanScoreDefinitionConfigApi>
export type BooleanScoreDefinitionConfigApiOutput = zod.output<typeof BooleanScoreDefinitionConfigApi>

export const ScoreDefinitionConfigApi = zod.union([
    CategoricalScoreDefinitionConfigApi,
    NumericScoreDefinitionConfigApi,
    BooleanScoreDefinitionConfigApi,
])

export type ScoreDefinitionConfigApi = zod.input<typeof ScoreDefinitionConfigApi>
export type ScoreDefinitionConfigApiOutput = zod.output<typeof ScoreDefinitionConfigApi>

export const ScoreDefinitionApi = zod.object({
    id: zod.uuid(),
    name: zod.string(),
    description: zod.string(),
    kind: ExperimentMetricKindEnumApi,
    archived: zod.boolean(),
    current_version: zod.number().describe('Current immutable configuration version number.'),
    current_version_id: zod
        .uuid()
        .nullable()
        .describe('UUID of the current version row. Matches `system.score_definitions.current_version_id` in HogQL.'),
    config: ScoreDefinitionConfigApi.describe('Current immutable scorer configuration.'),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the scorer.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    team: zod.number(),
})

export type ScoreDefinitionApi = zod.input<typeof ScoreDefinitionApi>
export type ScoreDefinitionApiOutput = zod.output<typeof ScoreDefinitionApi>

export const PaginatedScoreDefinitionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ScoreDefinitionApi),
})

export type PaginatedScoreDefinitionListApi = zod.input<typeof PaginatedScoreDefinitionListApi>
export type PaginatedScoreDefinitionListApiOutput = zod.output<typeof PaginatedScoreDefinitionListApi>

export const scoreDefinitionCreateApiNameMax = 255

export const scoreDefinitionCreateApiArchivedDefault = false

export const ScoreDefinitionCreateApi = zod.object({
    name: zod.string().max(scoreDefinitionCreateApiNameMax).describe('Human-readable scorer name.'),
    description: zod.string().nullish().describe('Optional human-readable description.'),
    kind: ExperimentMetricKindEnumApi.describe(
        'Scorer kind. This cannot be changed after creation.\n\n\* `categorical` - categorical\n\* `numeric` - numeric\n\* `boolean` - boolean'
    ),
    archived: zod
        .boolean()
        .default(scoreDefinitionCreateApiArchivedDefault)
        .describe('New scorers are always created as active.'),
    config: ScoreDefinitionConfigApi.describe('Initial immutable scorer configuration.'),
})

export type ScoreDefinitionCreateApi = zod.input<typeof ScoreDefinitionCreateApi>
export type ScoreDefinitionCreateApiOutput = zod.output<typeof ScoreDefinitionCreateApi>

export const patchedScoreDefinitionMetadataApiNameMax = 255

export const PatchedScoreDefinitionMetadataApi = zod.object({
    name: zod.string().max(patchedScoreDefinitionMetadataApiNameMax).optional().describe('Updated scorer name.'),
    description: zod.string().nullish().describe('Updated scorer description.'),
    archived: zod.boolean().optional().describe('Whether the scorer is archived.'),
})

export type PatchedScoreDefinitionMetadataApi = zod.input<typeof PatchedScoreDefinitionMetadataApi>
export type PatchedScoreDefinitionMetadataApiOutput = zod.output<typeof PatchedScoreDefinitionMetadataApi>

export const ScoreDefinitionNewVersionApi = zod.object({
    config: ScoreDefinitionConfigApi.describe('Next immutable scorer configuration.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            "Version number the caller observed before requesting this bump. If provided and it does not match the scorer's current version, the request fails with 409. Omit to skip the optimistic-concurrency check."
        ),
})

export type ScoreDefinitionNewVersionApi = zod.input<typeof ScoreDefinitionNewVersionApi>
export type ScoreDefinitionNewVersionApiOutput = zod.output<typeof ScoreDefinitionNewVersionApi>

export const SummarizeTypeEnumApi = zod.enum(['trace', 'event']).describe('\* `trace` - trace\n\* `event` - event')

export type SummarizeTypeEnumApi = zod.input<typeof SummarizeTypeEnumApi>
export type SummarizeTypeEnumApiOutput = zod.output<typeof SummarizeTypeEnumApi>

export const DetailModeValueEnumApi = zod
    .enum(['minimal', 'detailed'])
    .describe('\* `minimal` - minimal\n\* `detailed` - detailed')

export type DetailModeValueEnumApi = zod.input<typeof DetailModeValueEnumApi>
export type DetailModeValueEnumApiOutput = zod.output<typeof DetailModeValueEnumApi>

export const summarizeRequestApiModeDefault = `minimal`
export const summarizeRequestApiForceRefreshDefault = false

export const SummarizeRequestApi = zod.object({
    summarize_type: SummarizeTypeEnumApi.optional().describe(
        'Type of entity to summarize. Inferred automatically when using trace_id or generation_id.\n\n\* `trace` - trace\n\* `event` - event'
    ),
    mode: DetailModeValueEnumApi.default(summarizeRequestApiModeDefault).describe(
        "Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points\n\n\* `minimal` - minimal\n\* `detailed` - detailed"
    ),
    data: zod
        .unknown()
        .optional()
        .describe(
            'Data to summarize. For traces: {trace, hierarchy}. For events: {event}. Not required when using trace_id or generation_id.'
        ),
    force_refresh: zod
        .boolean()
        .default(summarizeRequestApiForceRefreshDefault)
        .describe('Force regenerate summary, bypassing cache'),
    model: zod.string().nullish().describe('LLM model to use (defaults based on provider)'),
    trace_id: zod
        .string()
        .optional()
        .describe(
            'Trace ID to summarize. The backend fetches the trace data automatically. Requires date_from for efficient lookup.'
        ),
    generation_id: zod
        .string()
        .optional()
        .describe(
            'Generation event UUID to summarize. The backend fetches the event data automatically. Requires date_from for efficient lookup.'
        ),
    date_from: zod
        .string()
        .nullish()
        .describe("Start of date range for ID-based lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d."),
    date_to: zod.string().nullish().describe('End of date range for ID-based lookup. Defaults to now.'),
})

export type SummarizeRequestApi = zod.input<typeof SummarizeRequestApi>
export type SummarizeRequestApiOutput = zod.output<typeof SummarizeRequestApi>

export const SummaryBulletApi = zod.object({
    text: zod.string(),
    line_refs: zod.string(),
})

export type SummaryBulletApi = zod.input<typeof SummaryBulletApi>
export type SummaryBulletApiOutput = zod.output<typeof SummaryBulletApi>

export const InterestingNoteApi = zod.object({
    text: zod.string(),
    line_refs: zod.string(),
})

export type InterestingNoteApi = zod.input<typeof InterestingNoteApi>
export type InterestingNoteApiOutput = zod.output<typeof InterestingNoteApi>

export const StructuredSummaryApi = zod.object({
    title: zod.string().describe('Concise title (no longer than 10 words) summarizing the trace\/event'),
    flow_diagram: zod.string().describe('Mermaid flowchart code showing the main flow'),
    summary_bullets: zod.array(SummaryBulletApi).describe('Main summary bullets'),
    interesting_notes: zod.array(InterestingNoteApi).describe('Interesting notes (0-2 for minimal, more for detailed)'),
})

export type StructuredSummaryApi = zod.input<typeof StructuredSummaryApi>
export type StructuredSummaryApiOutput = zod.output<typeof StructuredSummaryApi>

export const SummarizeResponseApi = zod.object({
    summary: StructuredSummaryApi.describe('Structured AI-generated summary with flow, bullets, and optional notes'),
    text_repr: zod.string().describe('Line-numbered text representation that the summary references'),
    metadata: zod.unknown().optional().describe('Metadata about the summarization'),
})

export type SummarizeResponseApi = zod.input<typeof SummarizeResponseApi>
export type SummarizeResponseApiOutput = zod.output<typeof SummarizeResponseApi>

export const batchCheckRequestApiTraceIdsMax = 100

export const batchCheckRequestApiModeDefault = `minimal`

export const BatchCheckRequestApi = zod.object({
    trace_ids: zod
        .array(zod.string())
        .max(batchCheckRequestApiTraceIdsMax)
        .describe('List of trace IDs to check for cached summaries'),
    mode: DetailModeValueEnumApi.default(batchCheckRequestApiModeDefault).describe(
        'Summary detail level to check for\n\n\* `minimal` - minimal\n\* `detailed` - detailed'
    ),
    model: zod.string().nullish().describe('LLM model used for cached summaries'),
})

export type BatchCheckRequestApi = zod.input<typeof BatchCheckRequestApi>
export type BatchCheckRequestApiOutput = zod.output<typeof BatchCheckRequestApi>

export const cachedSummaryApiCachedDefault = true

export const CachedSummaryApi = zod.object({
    trace_id: zod.string(),
    title: zod.string(),
    cached: zod.boolean().default(cachedSummaryApiCachedDefault),
})

export type CachedSummaryApi = zod.input<typeof CachedSummaryApi>
export type CachedSummaryApiOutput = zod.output<typeof CachedSummaryApi>

export const BatchCheckResponseApi = zod.object({
    summaries: zod.array(CachedSummaryApi),
})

export type BatchCheckResponseApi = zod.input<typeof BatchCheckResponseApi>
export type BatchCheckResponseApiOutput = zod.output<typeof BatchCheckResponseApi>

export const EventTypeEnumApi = zod
    .enum(['$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace'])
    .describe(
        '\* `$ai_generation` - $ai_generation\n\* `$ai_span` - $ai_span\n\* `$ai_embedding` - $ai_embedding\n\* `$ai_trace` - $ai_trace'
    )

export type EventTypeEnumApi = zod.input<typeof EventTypeEnumApi>
export type EventTypeEnumApiOutput = zod.output<typeof EventTypeEnumApi>

export const TextReprOptionsApi = zod.object({
    max_length: zod.number().optional().describe('Maximum length of generated text (default: 2000000)'),
    truncated: zod.boolean().optional().describe('Use truncation for long content within events (default: true)'),
    truncate_buffer: zod
        .number()
        .optional()
        .describe('Characters to show at start\/end when truncating (default: 1000)'),
    include_markers: zod
        .boolean()
        .optional()
        .describe('Use interactive markers for frontend vs plain text for backend\/LLM (default: true)'),
    collapsed: zod.boolean().optional().describe('Show summary vs full tree hierarchy for traces (default: false)'),
    include_metadata: zod.boolean().optional().describe('Include metadata in response'),
    include_hierarchy: zod.boolean().optional().describe('Include hierarchy information (for traces)'),
    max_depth: zod.number().optional().describe('Maximum depth for hierarchical rendering'),
    tools_collapse_threshold: zod
        .number()
        .optional()
        .describe('Number of tools before collapsing the list (default: 5)'),
    include_line_numbers: zod.boolean().optional().describe('Prefix each line with line number (default: false)'),
})

export type TextReprOptionsApi = zod.input<typeof TextReprOptionsApi>
export type TextReprOptionsApiOutput = zod.output<typeof TextReprOptionsApi>

export const TextReprRequestApi = zod.object({
    event_type: EventTypeEnumApi.describe(
        'Type of LLM event to stringify\n\n\* `$ai_generation` - $ai_generation\n\* `$ai_span` - $ai_span\n\* `$ai_embedding` - $ai_embedding\n\* `$ai_trace` - $ai_trace'
    ),
    data: zod.unknown().describe("Event data to stringify. For traces, should include 'trace' and 'hierarchy' fields."),
    options: TextReprOptionsApi.optional().describe('Optional configuration for text generation'),
})

export type TextReprRequestApi = zod.input<typeof TextReprRequestApi>
export type TextReprRequestApiOutput = zod.output<typeof TextReprRequestApi>

export const TextReprMetadataApi = zod.object({
    event_type: zod.string().optional(),
    event_id: zod.string().optional(),
    trace_id: zod.string().optional(),
    rendering: zod.string(),
    char_count: zod.number(),
    truncated: zod.boolean(),
    error: zod.string().optional(),
})

export type TextReprMetadataApi = zod.input<typeof TextReprMetadataApi>
export type TextReprMetadataApiOutput = zod.output<typeof TextReprMetadataApi>

export const TextReprResponseApi = zod.object({
    text: zod.string().describe('Generated text representation of the event'),
    metadata: TextReprMetadataApi.describe('Metadata about the text representation'),
})

export type TextReprResponseApi = zod.input<typeof TextReprResponseApi>
export type TextReprResponseApiOutput = zod.output<typeof TextReprResponseApi>

export const traceReviewScoreApiNumericValueRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,6})?$')

export const TraceReviewScoreApi = zod.object({
    id: zod.uuid(),
    definition_id: zod.uuid().describe('Stable scorer definition ID.'),
    definition_name: zod.string().describe('Human-readable scorer name.'),
    definition_kind: zod.string().describe('Scorer kind for this saved score.'),
    definition_archived: zod.boolean().describe('Whether the scorer is currently archived.'),
    definition_version_id: zod.uuid().describe('Immutable scorer version ID used to validate this score.'),
    definition_version: zod.number().describe('Immutable scorer version number used to validate this score.'),
    definition_config: ScoreDefinitionConfigApi.describe(
        'Immutable scorer configuration snapshot used to validate this score.'
    ),
    categorical_values: zod.array(zod.string()).nullable().describe('Categorical option keys selected for this score.'),
    numeric_value: zod.stringFormat('decimal', traceReviewScoreApiNumericValueRegExp).nullable(),
    boolean_value: zod.boolean().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type TraceReviewScoreApi = zod.input<typeof TraceReviewScoreApi>
export type TraceReviewScoreApiOutput = zod.output<typeof TraceReviewScoreApi>

export const TraceReviewApi = zod.object({
    id: zod.uuid(),
    trace_id: zod.string().describe('Trace ID for the review.'),
    trace_url: zod.url().describe('Absolute URL to the trace this review is attached to.'),
    comment: zod.string().nullable().describe('Optional comment or reasoning for the review.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi,
    reviewed_by: UserBasicApi.describe('User who last saved this review.'),
    scores: zod.array(TraceReviewScoreApi).describe('Saved scorer values for this review.'),
    team: zod.number(),
})

export type TraceReviewApi = zod.input<typeof TraceReviewApi>
export type TraceReviewApiOutput = zod.output<typeof TraceReviewApi>

export const PaginatedTraceReviewListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TraceReviewApi),
})

export type PaginatedTraceReviewListApi = zod.input<typeof PaginatedTraceReviewListApi>
export type PaginatedTraceReviewListApiOutput = zod.output<typeof PaginatedTraceReviewListApi>

export const traceReviewScoreWriteApiCategoricalValuesItemMax = 128

export const traceReviewScoreWriteApiNumericValueRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,6})?$')

export const TraceReviewScoreWriteApi = zod.object({
    definition_id: zod.uuid().describe('Stable scorer definition ID.'),
    definition_version_id: zod
        .uuid()
        .nullish()
        .describe("Optional immutable scorer version ID. Defaults to the scorer's current version."),
    categorical_values: zod
        .array(zod.string().max(traceReviewScoreWriteApiCategoricalValuesItemMax))
        .min(1)
        .nullish()
        .describe('Categorical option keys selected for this score.'),
    numeric_value: zod
        .stringFormat('decimal', traceReviewScoreWriteApiNumericValueRegExp)
        .nullish()
        .describe('Numeric value selected for this score.'),
    boolean_value: zod.boolean().nullish().describe('Boolean value selected for this score.'),
})

export type TraceReviewScoreWriteApi = zod.input<typeof TraceReviewScoreWriteApi>
export type TraceReviewScoreWriteApiOutput = zod.output<typeof TraceReviewScoreWriteApi>

export const traceReviewCreateApiTraceIdMax = 255

export const TraceReviewCreateApi = zod.object({
    trace_id: zod
        .string()
        .max(traceReviewCreateApiTraceIdMax)
        .describe('Trace ID for the review. Only one active review can exist per trace and team.'),
    comment: zod.string().nullish().describe('Optional comment or reasoning for the review.'),
    scores: zod
        .array(TraceReviewScoreWriteApi)
        .optional()
        .describe('Full desired score set for this review. Omit scorers you want to leave blank.'),
    queue_id: zod
        .uuid()
        .nullish()
        .describe(
            'Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.'
        ),
})

export type TraceReviewCreateApi = zod.input<typeof TraceReviewCreateApi>
export type TraceReviewCreateApiOutput = zod.output<typeof TraceReviewCreateApi>

export const patchedTraceReviewUpdateApiTraceIdMax = 255

export const PatchedTraceReviewUpdateApi = zod.object({
    trace_id: zod
        .string()
        .max(patchedTraceReviewUpdateApiTraceIdMax)
        .optional()
        .describe('Trace ID for the review. Only one active review can exist per trace and team.'),
    comment: zod.string().nullish().describe('Optional comment or reasoning for the review.'),
    scores: zod
        .array(TraceReviewScoreWriteApi)
        .optional()
        .describe('Full desired score set for this review. Omit scorers you want to leave blank.'),
    queue_id: zod
        .uuid()
        .nullish()
        .describe(
            'Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.'
        ),
})

export type PatchedTraceReviewUpdateApi = zod.input<typeof PatchedTraceReviewUpdateApi>
export type PatchedTraceReviewUpdateApiOutput = zod.output<typeof PatchedTraceReviewUpdateApi>

export const translateRequestApiTextMax = 10000

export const translateRequestApiTargetLanguageDefault = `en`
export const translateRequestApiTargetLanguageMax = 10

export const TranslateRequestApi = zod.object({
    text: zod.string().max(translateRequestApiTextMax).describe('The text to translate'),
    target_language: zod
        .string()
        .max(translateRequestApiTargetLanguageMax)
        .default(translateRequestApiTargetLanguageDefault)
        .describe("Target language code (default: 'en' for English)"),
})

export type TranslateRequestApi = zod.input<typeof TranslateRequestApi>
export type TranslateRequestApiOutput = zod.output<typeof TranslateRequestApi>

export const lLMPromptOutlineEntryApiLevelMax = 6

export const LLMPromptOutlineEntryApi = zod.object({
    level: zod.number().min(1).max(lLMPromptOutlineEntryApiLevelMax).describe('Markdown heading level (1-6).'),
    text: zod.string().describe('Heading text with markdown link syntax preserved.'),
})

export type LLMPromptOutlineEntryApi = zod.input<typeof LLMPromptOutlineEntryApi>
export type LLMPromptOutlineEntryApiOutput = zod.output<typeof LLMPromptOutlineEntryApi>

export const LLMPromptLabelSummaryApi = zod.object({
    name: zod.string().describe("Label name, e.g. 'production'."),
    version: zod.number().describe('Prompt version this label currently points to.'),
})

export type LLMPromptLabelSummaryApi = zod.input<typeof LLMPromptLabelSummaryApi>
export type LLMPromptLabelSummaryApiOutput = zod.output<typeof LLMPromptLabelSummaryApi>

export const LLMPromptListApi = zod.object({
    id: zod.uuid(),
    name: zod.string().describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
    config: zod
        .looseObject({})
        .nullish()
        .describe(
            "Optional JSON object with model parameters or any agent configuration (e.g. model, temperature, tools). Versioned with the prompt and returned as-is when fetching it. Don't store secrets here: config is returned to anyone who can read the prompt."
        ),
    version: zod.number(),
    version_description: zod
        .string()
        .nullable()
        .describe('Optional note describing what changed in this version. Set when the version is published.'),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.string(),
    outline: zod.array(LLMPromptOutlineEntryApi),
    labels: zod.array(zod.string()).describe('Names of the labels currently pointing at this version.'),
    activity_item_id: zod
        .string()
        .describe(
            "Key for this prompt's rows in the activity log, e.g. for the History tab. Derived from the name, at most 72 characters."
        ),
    prompt_preview: zod.string(),
    prompt_size_bytes: zod.number(),
    all_labels: zod.array(LLMPromptLabelSummaryApi),
})

export type LLMPromptListApi = zod.input<typeof LLMPromptListApi>
export type LLMPromptListApiOutput = zod.output<typeof LLMPromptListApi>

export const PaginatedLLMPromptListListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LLMPromptListApi),
})

export type PaginatedLLMPromptListListApi = zod.input<typeof PaginatedLLMPromptListListApi>
export type PaginatedLLMPromptListListApiOutput = zod.output<typeof PaginatedLLMPromptListListApi>

export const lLMPromptApiNameMax = 255

export const lLMPromptApiVersionDescriptionMax = 400

export const LLMPromptApi = zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(lLMPromptApiNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
    config: zod
        .looseObject({})
        .nullish()
        .describe(
            "Optional JSON object with model parameters or any agent configuration (e.g. model, temperature, tools). Versioned with the prompt and returned as-is when fetching it. Don't store secrets here: config is returned to anyone who can read the prompt."
        ),
    version: zod.number(),
    version_description: zod
        .string()
        .max(lLMPromptApiVersionDescriptionMax)
        .nullish()
        .describe('Optional note describing what changed in this version. Set when the version is published.'),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.string(),
    outline: zod.array(LLMPromptOutlineEntryApi),
    labels: zod.array(zod.string()).describe('Names of the labels currently pointing at this version.'),
    activity_item_id: zod
        .string()
        .describe(
            "Key for this prompt's rows in the activity log, e.g. for the History tab. Derived from the name, at most 72 characters."
        ),
})

export type LLMPromptApi = zod.input<typeof LLMPromptApi>
export type LLMPromptApiOutput = zod.output<typeof LLMPromptApi>

export const LLMPromptPublicApi = zod.object({
    id: zod.uuid(),
    name: zod.string(),
    prompt: zod.unknown().optional().describe("Full prompt content. Omitted when 'content=preview' or 'content=none'."),
    config: zod
        .looseObject({})
        .nullish()
        .describe(
            "JSON object with model parameters or any agent configuration stored with this version, or null when the version has none. Omitted when 'content=preview' or 'content=none'."
        ),
    prompt_preview: zod
        .string()
        .optional()
        .describe("First 160 characters of the prompt. Only present when 'content=preview'."),
    outline: zod
        .array(LLMPromptOutlineEntryApi)
        .describe('Flat list of markdown headings parsed from the prompt. Useful as a lightweight table of contents.'),
    version: zod.number(),
    label: zod
        .string()
        .optional()
        .describe('The label this prompt was fetched by. Only present when fetching with the label parameter.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.iso.datetime({ offset: true }),
})

export type LLMPromptPublicApi = zod.input<typeof LLMPromptPublicApi>
export type LLMPromptPublicApiOutput = zod.output<typeof LLMPromptPublicApi>

export const LLMPromptEditOperationApi = zod.object({
    old: zod.string().describe('Text to find in the current prompt. Must match exactly once.'),
    new: zod.string().describe('Replacement text.'),
})

export type LLMPromptEditOperationApi = zod.input<typeof LLMPromptEditOperationApi>
export type LLMPromptEditOperationApiOutput = zod.output<typeof LLMPromptEditOperationApi>

export const patchedLLMPromptPublishApiVersionDescriptionMax = 400

export const PatchedLLMPromptPublishApi = zod.object({
    prompt: zod
        .unknown()
        .optional()
        .describe('Full prompt payload to publish as a new version. Mutually exclusive with edits.'),
    edits: zod
        .array(LLMPromptEditOperationApi)
        .optional()
        .describe(
            "List of find\/replace operations to apply to the current prompt version. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with prompt."
        ),
    config: zod
        .looseObject({})
        .nullish()
        .describe(
            "JSON object with model parameters or any agent configuration to store with this version. If omitted, the current version's config is carried forward; pass null to clear it. Can be combined with either prompt or edits. Don't store secrets here: config is returned to anyone who can read the prompt."
        ),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
    version_description: zod
        .string()
        .max(patchedLLMPromptPublishApiVersionDescriptionMax)
        .optional()
        .describe('Optional note describing what changed in this version. Shown in the version history.'),
})

export type PatchedLLMPromptPublishApi = zod.input<typeof PatchedLLMPromptPublishApi>
export type PatchedLLMPromptPublishApiOutput = zod.output<typeof PatchedLLMPromptPublishApi>

export const lLMPromptDuplicateApiNewNameMax = 255

export const LLMPromptDuplicateApi = zod.object({
    new_name: zod
        .string()
        .max(lLMPromptDuplicateApiNewNameMax)
        .describe(
            'Name for the duplicated prompt. Must be unique and use only letters, numbers, hyphens, and underscores.'
        ),
})

export type LLMPromptDuplicateApi = zod.input<typeof LLMPromptDuplicateApi>
export type LLMPromptDuplicateApiOutput = zod.output<typeof LLMPromptDuplicateApi>

export const LLMPromptSetLabelApi = zod.object({
    version: zod
        .number()
        .min(1)
        .describe(
            'Prompt version this label should point to. If the label already exists on another version of the prompt, it is moved there.'
        ),
})

export type LLMPromptSetLabelApi = zod.input<typeof LLMPromptSetLabelApi>
export type LLMPromptSetLabelApiOutput = zod.output<typeof LLMPromptSetLabelApi>

export const LLMPromptLabelApi = zod.object({
    id: zod.uuid(),
    name: zod.string().describe("Label name, e.g. 'production'. Points to exactly one version of the prompt."),
    prompt_name: zod.string().describe('Name of the prompt this label belongs to.'),
    version: zod.number(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type LLMPromptLabelApi = zod.input<typeof LLMPromptLabelApi>
export type LLMPromptLabelApiOutput = zod.output<typeof LLMPromptLabelApi>

export const LLMPromptVersionSummaryApi = zod.object({
    id: zod.uuid(),
    version: zod.number(),
    version_description: zod.string().nullable(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    is_latest: zod.boolean(),
    labels: zod.array(zod.string()).describe('Names of the labels currently pointing at this version.'),
})

export type LLMPromptVersionSummaryApi = zod.input<typeof LLMPromptVersionSummaryApi>
export type LLMPromptVersionSummaryApiOutput = zod.output<typeof LLMPromptVersionSummaryApi>

export const LLMPromptResolveResponseApi = zod.object({
    prompt: LLMPromptApi,
    versions: zod.array(LLMPromptVersionSummaryApi),
    has_more: zod.boolean(),
    labels: zod
        .array(LLMPromptLabelApi)
        .describe(
            'All labels on this prompt with the version each one currently points to, across all versions (not just the returned page).'
        ),
})

export type LLMPromptResolveResponseApi = zod.input<typeof LLMPromptResolveResponseApi>
export type LLMPromptResolveResponseApiOutput = zod.output<typeof LLMPromptResolveResponseApi>

export const TaggerTypeEnumApi = zod.enum(['llm', 'hog']).describe('\* `llm` - LLM\n\* `hog` - Hog')

export type TaggerTypeEnumApi = zod.input<typeof TaggerTypeEnumApi>
export type TaggerTypeEnumApiOutput = zod.output<typeof TaggerTypeEnumApi>

export const tagDefinitionApiNameMax = 100

export const tagDefinitionApiDescriptionDefault = ``
export const tagDefinitionApiDescriptionMax = 500

export const TagDefinitionApi = zod.object({
    name: zod.string().max(tagDefinitionApiNameMax).describe('Tag identifier'),
    description: zod
        .string()
        .max(tagDefinitionApiDescriptionMax)
        .default(tagDefinitionApiDescriptionDefault)
        .describe('Description to help the LLM classify'),
})

export type TagDefinitionApi = zod.input<typeof TagDefinitionApi>
export type TagDefinitionApiOutput = zod.output<typeof TagDefinitionApi>

export const lLMTaggerConfigApiMinTagsDefault = 0
export const lLMTaggerConfigApiMinTagsMin = 0

export const LLMTaggerConfigApi = zod.object({
    prompt: zod.string().min(1).describe('Prompt instructing the LLM how to tag generations'),
    tags: zod.array(TagDefinitionApi).describe('Available tags the LLM can assign'),
    min_tags: zod
        .number()
        .min(lLMTaggerConfigApiMinTagsMin)
        .default(lLMTaggerConfigApiMinTagsDefault)
        .describe('Minimum number of tags to apply'),
    max_tags: zod.number().min(1).nullish().describe('Maximum number of tags to apply (null = no limit)'),
})

export type LLMTaggerConfigApi = zod.input<typeof LLMTaggerConfigApi>
export type LLMTaggerConfigApiOutput = zod.output<typeof LLMTaggerConfigApi>

export const HogTaggerConfigApi = zod.object({
    source: zod.string().min(1).describe('Hog source code to classify a generation into tags.'),
    tags: zod
        .array(TagDefinitionApi)
        .optional()
        .describe('Optional tag whitelist. Leave empty to allow any tag returned by the Hog code.'),
})

export type HogTaggerConfigApi = zod.input<typeof HogTaggerConfigApi>
export type HogTaggerConfigApiOutput = zod.output<typeof HogTaggerConfigApi>

export const TaggerConfigApi = zod.union([LLMTaggerConfigApi, HogTaggerConfigApi])

export type TaggerConfigApi = zod.input<typeof TaggerConfigApi>
export type TaggerConfigApiOutput = zod.output<typeof TaggerConfigApi>

export const taggerConditionApiIdMax = 100

export const taggerConditionApiRolloutPercentageDefault = 100
export const taggerConditionApiRolloutPercentageMin = 0
export const taggerConditionApiRolloutPercentageMax = 100

export const TaggerConditionApi = zod.object({
    id: zod.string().max(taggerConditionApiIdMax).describe('Stable identifier for this condition'),
    rollout_percentage: zod
        .number()
        .min(taggerConditionApiRolloutPercentageMin)
        .max(taggerConditionApiRolloutPercentageMax)
        .default(taggerConditionApiRolloutPercentageDefault)
        .describe('Percentage of matching events to apply this condition to'),
    properties: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe('Property filters that scope when this condition fires'),
})

export type TaggerConditionApi = zod.input<typeof TaggerConditionApi>
export type TaggerConditionApiOutput = zod.output<typeof TaggerConditionApi>

export const taggerModelConfigurationApiModelMax = 100

export const TaggerModelConfigurationApi = zod
    .object({
        provider: LLMProviderEnumApi.describe(
            'LLM provider to use for this tagger.\n\n\* `openai` - Openai\n\* `anthropic` - Anthropic\n\* `gemini` - Gemini\n\* `openrouter` - Openrouter\n\* `fireworks` - Fireworks\n\* `azure_openai` - Azure OpenAI\n\* `together_ai` - Together AI\n\* `minimax` - MiniMax\n\* `zeabur` - Zeabur AI Hub'
        ),
        model: zod
            .string()
            .max(taggerModelConfigurationApiModelMax)
            .describe('Provider model identifier to use for this tagger.'),
        provider_key_id: zod
            .uuid()
            .nullish()
            .describe(
                'Existing LLM provider key UUID for the current project. Do not invent this value; use a real provider key ID returned by PostHog, or omit\/null when no provider key should be pinned.'
            ),
        provider_key_name: zod.string().nullable(),
    })
    .describe('Nested serializer for model configuration.')

export type TaggerModelConfigurationApi = zod.input<typeof TaggerModelConfigurationApi>
export type TaggerModelConfigurationApiOutput = zod.output<typeof TaggerModelConfigurationApi>

export const taggerApiNameMax = 400

export const taggerApiTaggerTypeDefault = `llm`

export const TaggerApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(taggerApiNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    tagger_type: TaggerTypeEnumApi.default(taggerApiTaggerTypeDefault),
    tagger_config: TaggerConfigApi.describe(
        "Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}."
    ),
    conditions: zod.array(TaggerConditionApi).optional().describe('Conditions that scope when the tagger runs'),
    model_configuration: zod.union([TaggerModelConfigurationApi, zod.null()]).optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    deleted: zod.boolean().optional(),
})

export type TaggerApi = zod.input<typeof TaggerApi>
export type TaggerApiOutput = zod.output<typeof TaggerApi>

export const PaginatedTaggerListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaggerApi),
})

export type PaginatedTaggerListApi = zod.input<typeof PaginatedTaggerListApi>
export type PaginatedTaggerListApiOutput = zod.output<typeof PaginatedTaggerListApi>

export const taggerModelConfigurationWriteApiModelMax = 100

export const TaggerModelConfigurationWriteApi = zod.object({
    provider: LLMProviderEnumApi.describe(
        'LLM provider to use for this tagger.\n\n\* `openai` - Openai\n\* `anthropic` - Anthropic\n\* `gemini` - Gemini\n\* `openrouter` - Openrouter\n\* `fireworks` - Fireworks\n\* `azure_openai` - Azure OpenAI\n\* `together_ai` - Together AI\n\* `minimax` - MiniMax\n\* `zeabur` - Zeabur AI Hub'
    ),
    model: zod
        .string()
        .max(taggerModelConfigurationWriteApiModelMax)
        .describe('Provider model identifier to use for this tagger.'),
    provider_key_id: zod
        .uuid()
        .nullish()
        .describe(
            'Existing LLM provider key UUID for the current project. Do not invent this value; use a real provider key ID returned by PostHog, or omit\/null when no provider key should be pinned.'
        ),
})

export type TaggerModelConfigurationWriteApi = zod.input<typeof TaggerModelConfigurationWriteApi>
export type TaggerModelConfigurationWriteApiOutput = zod.output<typeof TaggerModelConfigurationWriteApi>

export const taggerCreateApiNameMax = 400

export const taggerCreateApiTaggerTypeDefault = `llm`

export const TaggerCreateApi = zod.object({
    name: zod.string().max(taggerCreateApiNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    tagger_type: TaggerTypeEnumApi.default(taggerCreateApiTaggerTypeDefault),
    tagger_config: TaggerConfigApi.describe(
        "Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}."
    ),
    conditions: zod.array(TaggerConditionApi).optional().describe('Conditions that scope when the tagger runs'),
    model_configuration: zod.union([TaggerModelConfigurationWriteApi, zod.null()]).optional(),
})

export type TaggerCreateApi = zod.input<typeof TaggerCreateApi>
export type TaggerCreateApiOutput = zod.output<typeof TaggerCreateApi>

export const taggerUpdateApiNameMax = 400

export const taggerUpdateApiTaggerTypeDefault = `llm`

export const TaggerUpdateApi = zod.object({
    name: zod.string().max(taggerUpdateApiNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    tagger_type: TaggerTypeEnumApi.default(taggerUpdateApiTaggerTypeDefault),
    tagger_config: TaggerConfigApi.describe(
        "Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}."
    ),
    conditions: zod.array(TaggerConditionApi).optional().describe('Conditions that scope when the tagger runs'),
    model_configuration: zod.union([TaggerModelConfigurationWriteApi, zod.null()]).optional(),
    deleted: zod.boolean().optional(),
})

export type TaggerUpdateApi = zod.input<typeof TaggerUpdateApi>
export type TaggerUpdateApiOutput = zod.output<typeof TaggerUpdateApi>

export const patchedTaggerUpdateApiNameMax = 400

export const patchedTaggerUpdateApiTaggerTypeDefault = `llm`

export const PatchedTaggerUpdateApi = zod.object({
    name: zod.string().max(patchedTaggerUpdateApiNameMax).optional(),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    tagger_type: TaggerTypeEnumApi.default(patchedTaggerUpdateApiTaggerTypeDefault),
    tagger_config: TaggerConfigApi.optional().describe(
        "Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}."
    ),
    conditions: zod.array(TaggerConditionApi).optional().describe('Conditions that scope when the tagger runs'),
    model_configuration: zod.union([TaggerModelConfigurationWriteApi, zod.null()]).optional(),
    deleted: zod.boolean().optional(),
})

export type PatchedTaggerUpdateApi = zod.input<typeof PatchedTaggerUpdateApi>
export type PatchedTaggerUpdateApiOutput = zod.output<typeof PatchedTaggerUpdateApi>

export const testHogTaggerTagApiNameMax = 100

export const testHogTaggerTagApiDescriptionDefault = ``
export const testHogTaggerTagApiDescriptionMax = 500

export const TestHogTaggerTagApi = zod.object({
    name: zod.string().max(testHogTaggerTagApiNameMax).describe('Tag identifier to allow in Hog test results.'),
    description: zod
        .string()
        .max(testHogTaggerTagApiDescriptionMax)
        .default(testHogTaggerTagApiDescriptionDefault)
        .describe('Optional description for the tag.'),
})

export type TestHogTaggerTagApi = zod.input<typeof TestHogTaggerTagApi>
export type TestHogTaggerTagApiOutput = zod.output<typeof TestHogTaggerTagApi>

export const testHogTaggerRequestApiSampleCountDefault = 5
export const testHogTaggerRequestApiSampleCountMax = 10

export const TestHogTaggerRequestApi = zod.object({
    source: zod
        .string()
        .min(1)
        .describe('Hog source code to test. Return a tag name string, a list of tag name strings, or null.'),
    sample_count: zod
        .number()
        .min(1)
        .max(testHogTaggerRequestApiSampleCountMax)
        .default(testHogTaggerRequestApiSampleCountDefault)
        .describe('Number of recent $ai_generation events to test against (1-10, default 5).'),
    tags: zod
        .array(TestHogTaggerTagApi)
        .optional()
        .describe('Optional tag whitelist. Returned tags outside this list are filtered out.'),
})

export type TestHogTaggerRequestApi = zod.input<typeof TestHogTaggerRequestApi>
export type TestHogTaggerRequestApiOutput = zod.output<typeof TestHogTaggerRequestApi>

export const TestHogTaggerResultItemApi = zod.object({
    event_uuid: zod.string().describe('UUID of the sampled $ai_generation event.'),
    trace_id: zod.string().nullish().describe('Trace ID if available.'),
    input_preview: zod.string().describe('First 200 characters of the generation input.'),
    output_preview: zod.string().describe('First 200 characters of the generation output.'),
    tags: zod.array(zod.string()).describe('Tag names returned by the Hog code.'),
    reasoning: zod.string().describe('Text written to stdout by the Hog code.'),
    error: zod.string().nullish().describe('Error message if the Hog code failed.'),
})

export type TestHogTaggerResultItemApi = zod.input<typeof TestHogTaggerResultItemApi>
export type TestHogTaggerResultItemApiOutput = zod.output<typeof TestHogTaggerResultItemApi>

export const TestHogTaggerResponseApi = zod.object({
    results: zod.array(TestHogTaggerResultItemApi).describe('Per-event Hog tagger test results.'),
    message: zod.string().optional().describe('Optional message, for example when no recent AI events were found.'),
})

export type TestHogTaggerResponseApi = zod.input<typeof TestHogTaggerResponseApi>
export type TestHogTaggerResponseApiOutput = zod.output<typeof TestHogTaggerResponseApi>
