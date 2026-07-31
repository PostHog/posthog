/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    BatchCheckRequestApi,
    ClusteringConfigSetEventFiltersApi,
    ClusteringJobApi,
    ClusteringRunRequestApi,
    DatasetApi,
    DatasetItemApi,
    EvaluationApi,
    EvaluationConfigSetActiveKeyRequestApi,
    EvaluationReportApi,
    EvaluationReportUpdateApi,
    EvaluationRunRequestApi,
    EvaluationSummaryRequestApi,
    LLMPromptApi,
    LLMPromptDuplicateApi,
    LLMPromptSetLabelApi,
    LLMProviderKeyApi,
    OfflineExperimentItemsRequestApi,
    ParserRecipeApi,
    PatchedClusteringJobApi,
    PatchedDatasetApi,
    PatchedDatasetItemApi,
    PatchedEvaluationApi,
    PatchedEvaluationReportUpdateApi,
    PatchedLLMPromptPublishApi,
    PatchedLLMProviderKeyApi,
    PatchedParserRecipeApi,
    PatchedReviewQueueItemUpdateApi,
    PatchedReviewQueueUpdateApi,
    PatchedScoreDefinitionMetadataApi,
    PatchedTaggerUpdateApi,
    PatchedTraceReviewUpdateApi,
    ReviewQueueCreateApi,
    ReviewQueueItemCreateApi,
    ScoreDefinitionCreateApi,
    ScoreDefinitionNewVersionApi,
    SummarizeRequestApi,
    TaggerCreateApi,
    TaggerUpdateApi,
    TestHogRequestApi,
    TestHogTaggerRequestApi,
    TextReprRequestApi,
    TraceReviewCreateApi,
    TranslateRequestApi,
} from './api.zod.schemas'

export const DatasetItemsCreateBody = DatasetItemApi

export const DatasetItemsUpdateBody = DatasetItemApi

export const DatasetItemsPartialUpdateBody = PatchedDatasetItemApi

export const DatasetsCreateBody = DatasetApi

export const DatasetsUpdateBody = DatasetApi

export const DatasetsPartialUpdateBody = PatchedDatasetApi

/**
 * Create a new evaluation run.
 *
 * This endpoint validates the request and enqueues a Temporal workflow
 * to asynchronously execute the evaluation.
 */
export const EvaluationRunsCreateBody = EvaluationRunRequestApi

export const EvaluationsCreateBody = EvaluationApi

export const EvaluationsUpdateBody = EvaluationApi

export const EvaluationsPartialUpdateBody = PatchedEvaluationApi

/**
 * Test Hog evaluation code against sample events without saving.
 */
export const EvaluationsTestHogCreateBody = TestHogRequestApi

/**
 * Team-level clustering configuration (event filters for automated pipelines).
 */
export const LlmAnalyticsClusteringConfigSetEventFiltersCreateBody = ClusteringConfigSetEventFiltersApi

/**
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsCreateBody = ClusteringJobApi

/**
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsUpdateBody = ClusteringJobApi

/**
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsPartialUpdateBody = PatchedClusteringJobApi

/**
 * Trigger a new clustering workflow run.
 *
 * This endpoint validates the request parameters and starts a Temporal workflow
 * to perform trace clustering with the specified configuration.
 */
export const LlmAnalyticsClusteringRunsCreateBody = ClusteringRunRequestApi

/**
 * Set the active provider key for evaluations
 */
export const LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody = EvaluationConfigSetActiveKeyRequestApi

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsCreateBody = EvaluationReportApi

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsUpdateBody = EvaluationReportUpdateApi

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsPartialUpdateBody = PatchedEvaluationReportUpdateApi

/**
 *
 * Generate an AI-powered summary of evaluation results.
 *
 * This endpoint analyzes evaluation runs and identifies patterns in passing
 * and failing evaluations, providing actionable recommendations.
 *
 * Data is fetched server-side by evaluation ID to ensure data integrity.
 *
 * **Use Cases:**
 * - Understand why evaluations are passing or failing
 * - Identify systematic issues in LLM responses
 * - Get recommendations for improving response quality
 * - Review patterns across many evaluation runs at once
 *
 */
export const LlmAnalyticsEvaluationSummaryCreateBody = EvaluationSummaryRequestApi

export const LlmAnalyticsOfflineEvaluationsExperimentItemsCreateBody = OfflineExperimentItemsRequestApi

export const LlmAnalyticsParserRecipesCreateBody = ParserRecipeApi

export const LlmAnalyticsParserRecipesPartialUpdateBody = PatchedParserRecipeApi

export const LlmAnalyticsProviderKeysCreateBody = LLMProviderKeyApi

export const LlmAnalyticsProviderKeysUpdateBody = LLMProviderKeyApi

export const LlmAnalyticsProviderKeysPartialUpdateBody = PatchedLLMProviderKeyApi

export const LlmAnalyticsProviderKeysValidateCreateBody = LLMProviderKeyApi

export const LlmAnalyticsReviewQueueItemsCreateBody = ReviewQueueItemCreateApi

export const LlmAnalyticsReviewQueueItemsPartialUpdateBody = PatchedReviewQueueItemUpdateApi

export const LlmAnalyticsReviewQueuesCreateBody = ReviewQueueCreateApi

export const LlmAnalyticsReviewQueuesPartialUpdateBody = PatchedReviewQueueUpdateApi

export const LlmAnalyticsScoreDefinitionsCreateBody = ScoreDefinitionCreateApi

export const LlmAnalyticsScoreDefinitionsPartialUpdateBody = PatchedScoreDefinitionMetadataApi

export const LlmAnalyticsScoreDefinitionsNewVersionCreateBody = ScoreDefinitionNewVersionApi

/**
 *
 * Generate an AI-powered summary of an LLM trace or event.
 *
 * This endpoint analyzes the provided trace/event, generates a line-numbered text
 * representation, and uses an LLM to create a concise summary with line references.
 *
 * **Two ways to use this endpoint:**
 *
 * 1. **By ID (recommended):** Pass `trace_id` or `generation_id` with an optional `date_from`/`date_to`.
 *    The backend fetches the data automatically. `summarize_type` is inferred.
 * 2. **By data:** Pass the full trace/event data blob in `data` with `summarize_type`.
 *    This is how the frontend uses it.
 *
 * **Summary Format:**
 * - Title (concise, max 10 words)
 * - Mermaid flow diagram showing the main flow
 * - 3-10 summary bullets with line references
 * - "Interesting Notes" section for failures, successes, or unusual patterns
 * - Line references in [L45] or [L45-52] format pointing to relevant sections
 *
 * The response includes the structured summary, the text representation, and metadata.
 *
 */
export const LlmAnalyticsSummarizationCreateBody = SummarizeRequestApi

/**
 *
 * Check which traces have cached summaries available.
 *
 * This endpoint allows batch checking of multiple trace IDs to see which ones
 * have cached summaries. Returns only the traces that have cached summaries
 * with their titles.
 *
 * **Use Cases:**
 * - Load cached summaries on session view load
 * - Avoid unnecessary LLM calls for already-summarized traces
 * - Display summary previews without generating new summaries
 *
 */
export const LlmAnalyticsSummarizationBatchCheckCreateBody = BatchCheckRequestApi

/**
 *
 * Generate a human-readable text representation of an LLM trace event.
 *
 * This endpoint converts AI observability events ($ai_generation, $ai_span, $ai_embedding, or $ai_trace)
 * into formatted text representations suitable for display, logging, or analysis.
 *
 * **Supported Event Types:**
 * - `$ai_generation`: Individual LLM API calls with input/output messages
 * - `$ai_span`: Logical spans with state transitions
 * - `$ai_embedding`: Embedding generation events (text input → vector)
 * - `$ai_trace`: Full traces with hierarchical structure
 *
 * **Options:**
 * - `max_length`: Maximum character count (default: 2000000)
 * - `truncated`: Enable middle-content truncation within events (default: true)
 * - `truncate_buffer`: Characters at start/end when truncating (default: 1000)
 * - `include_markers`: Use interactive markers vs plain text indicators (default: true)
 *   - Frontend: set true for `<<<TRUNCATED|base64|...>>>` markers
 *   - Backend/LLM: set false for `... (X chars truncated) ...` text
 * - `collapsed`: Show summary vs full trace tree (default: false)
 * - `include_hierarchy`: Include tree structure for traces (default: true)
 * - `max_depth`: Maximum depth for hierarchical rendering (default: unlimited)
 * - `tools_collapse_threshold`: Number of tools before auto-collapsing list (default: 5)
 *   - Tool lists >5 items show `<<<TOOLS_EXPANDABLE|...>>>` marker for frontend
 *   - Or `[+] AVAILABLE TOOLS: N` for backend when `include_markers: false`
 * - `include_line_numbers`: Prefix each line with line number like L001:, L010: (default: false)
 *
 * **Use Cases:**
 * - Frontend display: `truncated: true, include_markers: true, include_line_numbers: true`
 * - Backend LLM context (summary): `truncated: true, include_markers: false, collapsed: true`
 * - Backend LLM context (full): `truncated: false`
 *
 * The response includes the formatted text and metadata about the rendering.
 *
 */
export const LlmAnalyticsTextReprCreateBody = TextReprRequestApi

export const LlmAnalyticsTraceReviewsCreateBody = TraceReviewCreateApi

export const LlmAnalyticsTraceReviewsPartialUpdateBody = PatchedTraceReviewUpdateApi

/**
 * Translate text to target language.
 */
export const LlmAnalyticsTranslateCreateBody = TranslateRequestApi

export const LlmPromptsCreateBody = LLMPromptApi

export const LlmPromptsNamePartialUpdateBody = PatchedLLMPromptPublishApi

export const LlmPromptsNameDuplicateCreateBody = LLMPromptDuplicateApi

export const LlmPromptsNameLabelsUpdateBody = LLMPromptSetLabelApi

export const TaggersCreateBody = TaggerCreateApi

export const TaggersUpdateBody = TaggerUpdateApi

export const TaggersPartialUpdateBody = PatchedTaggerUpdateApi

/**
 * Test Hog tagger code against sample events without saving.
 */
export const TaggersTestHogCreateBody = TestHogTaggerRequestApi
