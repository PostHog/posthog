"""Constants for batch trace summarization workflows."""

from temporalio.common import RetryPolicy

from products.llm_analytics.backend.summarization.models import GeminiModel, SummarizationMode, SummarizationProvider

# Window processing configuration
DEFAULT_MAX_TRACES_PER_WINDOW = 100  # Max traces to process per window (conservative for worst-case 30s/trace)
DEFAULT_BATCH_SIZE = 5  # Number of traces to process in parallel per batch
DEFAULT_MODE = SummarizationMode.DETAILED
DEFAULT_WINDOW_MINUTES = 60  # Process traces from last N minutes (matches schedule frequency)
DEFAULT_PROVIDER = SummarizationProvider.GEMINI
DEFAULT_MODEL = GeminiModel.GEMINI_3_FLASH_PREVIEW

# Max text representation length by provider (in characters)
# Gemini models have ~1M token context. At typical 2.5:1 char/token ratio,
# 1.5M chars = ~600K tokens, leaving room for system prompt and output.
# OpenAI GPT-4.1-mini has 1M token context with better token efficiency,
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
SUMMARIZE_RETRY_POLICY = RetryPolicy(maximum_attempts=2)  # Fewer retries due to LLM cost
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

# Event schema
EVENT_NAME_TRACE_SUMMARY = "$ai_trace_summary"

# Team allowlist - only these teams will be processed by the coordinator
# Empty list means no teams will be processed (coordinator skips)
ALLOWED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    112495,  # Dogfooding project
]

# Temporal configuration
WORKFLOW_NAME = "llma-trace-summarization"
COORDINATOR_WORKFLOW_NAME = "llma-trace-summarization-coordinator"
