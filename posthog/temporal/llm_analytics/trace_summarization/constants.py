"""Constants for batch trace summarization workflows."""

from temporalio.common import RetryPolicy

# Window processing configuration
DEFAULT_MAX_TRACES_PER_WINDOW = 100  # Max traces to process per window (conservative for worst-case 30s/trace)
DEFAULT_BATCH_SIZE = 5  # Number of traces to process in parallel per batch
DEFAULT_MODE = "detailed"  # Summary detail level: 'minimal' or 'detailed' (detailed provides more context for embeddings/clustering)
DEFAULT_WINDOW_MINUTES = 60  # Process traces from last N minutes (matches schedule frequency)
DEFAULT_WORKFLOW_MODEL = "gpt-4.1-mini"  # Default LLM model for workflow (1M token context window)

# Text representation size limits
# GPT-4.1-mini has 1M token context (~4M chars), using 2M chars to leave room for prompt/output
MAX_TEXT_REPR_LENGTH = 2_000_000

# Timeout configuration (in seconds)
SAMPLE_TIMEOUT_SECONDS = 300  # 5 minutes for sampling query
FETCH_HIERARCHY_TIMEOUT_SECONDS = 60  # 1 minute per trace hierarchy fetch (increased for robustness)
GENERATE_SUMMARY_TIMEOUT_SECONDS = 300  # 5 minutes per summary generation (increased for LLM API latency/rate limits)
EMIT_EVENTS_TIMEOUT_SECONDS = 60  # 1 minute for batch event emission
EMBED_TIMEOUT_SECONDS = 60  # 1 minute for batch embedding (Kafka is async)

# Workflow-level timeouts (in minutes)
WORKFLOW_EXECUTION_TIMEOUT_MINUTES = 120  # Max time for single team workflow (increased with longer activity timeouts)

# Retry configuration
MAX_RETRY_ATTEMPTS_SAMPLE = 3  # Retries for sampling activity
MAX_RETRY_ATTEMPTS_FETCH = 3  # Retries for fetching trace hierarchy
MAX_RETRY_ATTEMPTS_SUMMARIZE = 2  # Retries for LLM summarization (fewer due to cost)
MAX_RETRY_ATTEMPTS_EMIT = 3  # Retries for event emission

# Retry policies
SAMPLE_RETRY_POLICY = RetryPolicy(maximum_attempts=MAX_RETRY_ATTEMPTS_SAMPLE)
SUMMARIZE_RETRY_POLICY = RetryPolicy(maximum_attempts=MAX_RETRY_ATTEMPTS_SUMMARIZE)
EMBED_RETRY_POLICY = RetryPolicy(maximum_attempts=MAX_RETRY_ATTEMPTS_EMIT)

# Coordinator retry policies
COORDINATOR_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

# Error threshold for workflow failure
MAX_ERROR_RATE_THRESHOLD = 0.5  # Fail workflow if >50% of summaries fail

# Event schema
EVENT_NAME_TRACE_SUMMARY = "$ai_trace_summary"  # Event name for summary storage

# Team allowlist - only these teams will be processed by the coordinator
# Empty list means all teams are allowed
ALLOWED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    112495,  # Dogfooding project
]

# Temporal configuration
WORKFLOW_NAME = "batch-trace-summarization"
TASK_QUEUE = "llm-analytics-queue"

# Embedding rendering types (for document_embeddings table)
LLMA_TRACE_MINIMAL_RENDERING = "llma_trace_minimal"
LLMA_TRACE_DETAILED_RENDERING = "llma_trace_detailed"
