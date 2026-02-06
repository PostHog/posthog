"""Constants for batch trace summarization workflows."""

from datetime import timedelta

from temporalio.common import RetryPolicy

from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode

# Window processing configuration
DEFAULT_MAX_ITEMS_PER_WINDOW = (
    15  # Max items to process per window (targets ~2500 summaries in 7-day clustering window)
)
DEFAULT_BATCH_SIZE = 5  # Number of generations to process in parallel
DEFAULT_TRACE_BATCH_SIZE = 1  # Traces processed sequentially - formatting is CPU-intensive and holds the GIL
DEFAULT_MODE = SummarizationMode.DETAILED
DEFAULT_WINDOW_MINUTES = 60  # Process traces from last N minutes (matches schedule frequency)
DEFAULT_WINDOW_OFFSET_MINUTES = 30  # Offset window into the past so traces have time to fully complete
DEFAULT_MODEL = OpenAIModel.GPT_4_1_NANO

# Max text representation length (in characters)
# GPT-4.1-nano has 1M token context. At typical 2.5:1 char/token ratio,
# 2M chars = ~800K tokens, leaving room for system prompt and output.
MAX_TEXT_REPR_LENGTH = 2_000_000

# Schedule configuration
SCHEDULE_INTERVAL_HOURS = 1  # How often the coordinator runs

# Coordinator concurrency settings
DEFAULT_MAX_CONCURRENT_TEAMS = 5  # Max teams to process in parallel

# Timeout configuration (in seconds)
SAMPLE_TIMEOUT_SECONDS = 900  # 15 minutes for sampling query (buffer above QUERY_ASYNC 600s ClickHouse timeout)
GENERATE_SUMMARY_TIMEOUT_SECONDS = (
    900  # 15 minutes per summary generation (large traces can produce ~800K token LLM calls)
)

# Heartbeat timeouts - allows Temporal to detect dead workers faster than
# waiting for the full start_to_close_timeout to expire. Activities must
# send heartbeats within this interval or Temporal will consider them failed
# and retry on another worker.
SAMPLE_HEARTBEAT_TIMEOUT = timedelta(seconds=120)  # 2 minutes - sampling has long CH queries
SUMMARIZE_HEARTBEAT_TIMEOUT: timedelta | None = (
    None  # Disabled - large trace formatting holds the GIL and blocks heartbeats. Relies on start_to_close (15 min) and schedule_to_close (45 min) for stuck activity detection.
)

# Schedule-to-close timeouts - caps total time including all retry attempts,
# backoff intervals, and queue time. Prevents runaway retries from blocking
# the workflow indefinitely when something is fundamentally broken.
SAMPLE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=1800)  # 30 min total for sampling (3 attempts * 900s + backoff)
SUMMARIZE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(
    seconds=2700
)  # 45 min total per summary (3 full attempts * 900s + backoff)

# Workflow-level timeouts (in minutes)
WORKFLOW_EXECUTION_TIMEOUT_MINUTES = (
    180  # Max time for single team workflow (5 batches * 45 min worst case, usually ~75 min)
)
COORDINATOR_EXECUTION_TIMEOUT_MINUTES = (
    240  # 4 hours - 211 teams with 3 concurrent, most finish instantly but a few hit child timeout
)

# Retry policies
SAMPLE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    non_retryable_error_types=["ValueError", "TypeError"],
)
# Summarize retries with exponential backoff for rate limit handling (429s)
# 15s initial with 2x backoff handles most rate limit scenarios
SUMMARIZE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=4,
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    non_retryable_error_types=["ValueError", "TypeError"],
)
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

# Event schema
EVENT_NAME_TRACE_SUMMARY = "$ai_trace_summary"
EVENT_NAME_GENERATION_SUMMARY = "$ai_generation_summary"  # For generation-level summarization

# Document types for embeddings
GENERATION_DOCUMENT_TYPE = "llm-generation-summary-detailed"  # For generation-level embeddings

# Generation-level configuration
DEFAULT_MAX_GENERATIONS_PER_WINDOW = 50  # Higher than traces - generations are simpler units

# Temporal configuration
WORKFLOW_NAME = "llma-trace-summarization"
COORDINATOR_WORKFLOW_NAME = "llma-trace-summarization-coordinator"
COORDINATOR_SCHEDULE_ID = "llma-trace-summarization-coordinator-schedule"
CHILD_WORKFLOW_ID_PREFIX = "llma-trace-summarization-team"

# Generation-level schedule configuration (reuses same coordinator workflow with different inputs)
GENERATION_COORDINATOR_SCHEDULE_ID = "llma-generation-summarization-coordinator-schedule"
GENERATION_CHILD_WORKFLOW_ID_PREFIX = "llma-generation-summarization-team"
