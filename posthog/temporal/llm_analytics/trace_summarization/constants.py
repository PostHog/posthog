"""Constants for batch trace summarization workflows."""

from datetime import timedelta

from temporalio.common import RetryPolicy

from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode

# Window processing configuration
DEFAULT_MAX_ITEMS_PER_WINDOW = (
    15  # Max items to process per window (targets ~2500 summaries in 7-day clustering window)
)
DEFAULT_BATCH_SIZE = 5  # Number of generations to process in parallel
DEFAULT_TRACE_BATCH_SIZE = 4  # Traces processed in small parallel batches
DEFAULT_MODE = SummarizationMode.DETAILED
DEFAULT_WINDOW_MINUTES = 60  # Process traces from last N minutes (matches schedule frequency)
DEFAULT_WINDOW_OFFSET_MINUTES = 30  # Offset window into the past so traces have time to fully complete
DEFAULT_MODEL = OpenAIModel.GPT_4_1_NANO

# Max text representation length (in characters)
# GPT-4.1-nano has 1M token context. At typical 2.5:1 char/token ratio,
# 2M chars = ~800K tokens, leaving room for system prompt and output.
MAX_TEXT_REPR_LENGTH = 2_000_000

# Max estimated raw trace size (in characters) before formatting.
# Traces exceeding this are skipped — formatting huge traces is CPU-intensive
# and can block the worker for 10+ minutes. Estimated cheaply from
# sum(len(str(properties))) per event before entering the formatter.
MAX_RAW_TRACE_SIZE = 5_000_000

# Max events per trace for sampling. Traces with more events than this are
# excluded at the ClickHouse query level during sampling, preventing them
# from ever reaching the CPU-intensive formatting activity.
MAX_TRACE_EVENTS_LIMIT = 50

# Max total estimated properties size (in characters) per trace for sampling.
# Estimated at the ClickHouse level as sum(length(properties)) across all events
# in a trace. Traces exceeding this are excluded during sampling, preventing
# oversized traces from reaching the CPU-intensive formatting activity — even if
# they have few events. Complements MAX_TRACE_EVENTS_LIMIT which only filters
# by event count. Set lower than MAX_RAW_TRACE_SIZE (5M) to be conservative —
# formatting traces in the 2-5M range is still CPU-intensive enough to block
# workers for minutes.
MAX_TRACE_PROPERTIES_SIZE = 2_000_000

# AI event types used in trace queries (sampling and fetching)
AI_EVENT_TYPES = (
    "$ai_span",
    "$ai_generation",
    "$ai_embedding",
    "$ai_metric",
    "$ai_feedback",
    "$ai_trace",
)

# Expand the time window by this amount each side when fetching traces,
# so traces that started just before/after the window are still found.
TRACE_CAPTURE_RANGE = timedelta(minutes=10)

# Schedule configuration
SCHEDULE_INTERVAL_HOURS = 1  # How often the coordinator runs

# Coordinator concurrency settings
DEFAULT_MAX_CONCURRENT_TEAMS = 5  # Max teams to process in parallel

# Timeout configuration (in seconds)
SAMPLE_TIMEOUT_SECONDS = 900  # 15 minutes for sampling query (buffer above QUERY_ASYNC 600s ClickHouse timeout)

# Heartbeat timeouts - allows Temporal to detect dead workers faster than
# waiting for the full start_to_close_timeout to expire. Activities must
# send heartbeats within this interval or Temporal will consider them failed
# and retry on another worker.
SAMPLE_HEARTBEAT_TIMEOUT = timedelta(seconds=120)  # 2 minutes - sampling has long CH queries

# Schedule-to-close timeouts - caps total time including all retry attempts,
# backoff intervals, and queue time. Prevents runaway retries from blocking
# the workflow indefinitely when something is fundamentally broken.
SAMPLE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=1200)  # 20 min total for sampling (2 attempts * 900s + backoff)

# Activity 1: Fetch + format + store in Redis (fast, ClickHouse-bound)
FETCH_AND_FORMAT_START_TO_CLOSE_TIMEOUT = timedelta(seconds=120)
FETCH_AND_FORMAT_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(
    seconds=360
)  # 6 min total for fetch+format (2 attempts * 120s + backoff)
FETCH_AND_FORMAT_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
FETCH_AND_FORMAT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# Activity 2: Summarize + save (slow, I/O-bound LLM call - heartbeats work)
SUMMARIZE_AND_SAVE_START_TO_CLOSE_TIMEOUT = timedelta(seconds=900)
SUMMARIZE_AND_SAVE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=1200)  # 20 min total (2 attempts * 900s + backoff)
SUMMARIZE_AND_SAVE_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
SUMMARIZE_AND_SAVE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    non_retryable_error_types=["ValueError", "TypeError", "TextReprExpiredError"],
)

# Workflow-level timeouts (in minutes)
WORKFLOW_EXECUTION_TIMEOUT_MINUTES = 30  # Max time for single team workflow — must be well under coordinator timeout
COORDINATOR_EXECUTION_TIMEOUT_MINUTES = 55  # Must finish before next hourly trigger to avoid silent skips

# Retry policies
SAMPLE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    non_retryable_error_types=["ValueError", "TypeError"],
)
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

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
