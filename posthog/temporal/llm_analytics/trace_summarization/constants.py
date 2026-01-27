"""Constants for batch trace summarization workflows."""

from datetime import timedelta

from temporalio.common import RetryPolicy

from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode, SummarizationProvider

# Window processing configuration
DEFAULT_MAX_ITEMS_PER_WINDOW = 10  # Max items to process per window (conservative for worst-case 30s/item)
DEFAULT_BATCH_SIZE = 3  # Number of traces to process in parallel (reduced to avoid rate limits)
DEFAULT_MODE = SummarizationMode.DETAILED
DEFAULT_WINDOW_MINUTES = 60  # Process traces from last N minutes (matches schedule frequency)
DEFAULT_PROVIDER = SummarizationProvider.OPENAI
DEFAULT_MODEL = OpenAIModel.GPT_4_1_NANO

# Max text representation length by provider (in characters)
# Gemini models have ~1M token context. At typical 2.5:1 char/token ratio,
# 1.5M chars = ~600K tokens, leaving room for system prompt and output.
# OpenAI GPT-4.1-nano has 1M token context with better token efficiency,
# so 2M chars = ~800K tokens is safe.
MAX_LENGTH_BY_PROVIDER: dict[SummarizationProvider, int] = {
    SummarizationProvider.GEMINI: 1_500_000,
    SummarizationProvider.OPENAI: 2_000_000,
}

# Schedule configuration
SCHEDULE_INTERVAL_HOURS = 1  # How often the coordinator runs

# Timeout configuration (in seconds)
SAMPLE_TIMEOUT_SECONDS = 300  # 5 minutes for sampling query
GENERATE_SUMMARY_TIMEOUT_SECONDS = 300  # 5 minutes per summary generation (increased for LLM API latency/rate limits)

# Workflow-level timeouts (in minutes)
WORKFLOW_EXECUTION_TIMEOUT_MINUTES = 120  # Max time for single team workflow (increased with longer activity timeouts)

# Retry policies
SAMPLE_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
# Summarize retries with exponential backoff for rate limit handling (429s)
# 15s initial with 2x backoff handles most rate limit scenarios
SUMMARIZE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=4,
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
)
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

# Event schema
EVENT_NAME_TRACE_SUMMARY = "$ai_trace_summary"
EVENT_NAME_GENERATION_SUMMARY = "$ai_generation_summary"  # For generation-level summarization

# Document types for embeddings
GENERATION_DOCUMENT_TYPE = "llm-generation-summary-detailed"  # For generation-level embeddings

# Generation-level configuration
DEFAULT_MAX_GENERATIONS_PER_WINDOW = 50  # Higher than traces - generations are simpler units

# Team allowlist - only these teams will be processed by the coordinator
# Empty list means no teams will be processed (coordinator skips)
ALLOWED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    # Dogfooding projects
    112495,
    148051,
    140227,
    237906,
    294356,
]

# Temporal configuration
WORKFLOW_NAME = "llma-trace-summarization"
COORDINATOR_WORKFLOW_NAME = "llma-trace-summarization-coordinator"
COORDINATOR_SCHEDULE_ID = "llma-trace-summarization-coordinator-schedule"
CHILD_WORKFLOW_ID_PREFIX = "llma-trace-summarization-team"

# Generation-level schedule configuration (reuses same coordinator workflow with different inputs)
GENERATION_COORDINATOR_SCHEDULE_ID = "llma-generation-summarization-coordinator-schedule"
