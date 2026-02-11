"""Configuration constants for trace clustering workflow."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Clustering parameters
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_SAMPLES = 1500
DEFAULT_MIN_K = 2
DEFAULT_MAX_K = 10

# Minimum traces required for clustering
MIN_TRACES_FOR_CLUSTERING = 20

# Coordinator concurrency settings
DEFAULT_MAX_CONCURRENT_TEAMS = 4  # Max teams to process in parallel

# Workflow timeouts
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=12)  # Must be less than daily schedule interval to avoid blocking
# Temporal configuration
WORKFLOW_NAME = "llma-trace-clustering"
COORDINATOR_WORKFLOW_NAME = "llma-trace-clustering-coordinator"
COORDINATOR_SCHEDULE_ID = "llma-trace-clustering-coordinator-schedule"
CHILD_WORKFLOW_ID_PREFIX = "llma-trace-clustering-team"

# Generation-level schedule configuration (reuses same coordinator workflow with different inputs)
GENERATION_COORDINATOR_SCHEDULE_ID = "llma-generation-clustering-coordinator-schedule"
GENERATION_CHILD_WORKFLOW_ID_PREFIX = "llma-generation-clustering-team"

# Activity timeouts (per activity type, per single attempt)
COMPUTE_ACTIVITY_TIMEOUT = timedelta(seconds=120)  # Fetch + clustering + distances
LLM_ACTIVITY_TIMEOUT = timedelta(seconds=600)  # 10 minutes for full labeling agent run (LangGraph multi-turn)
EMIT_ACTIVITY_TIMEOUT = timedelta(seconds=60)  # ClickHouse write

# Heartbeat timeouts - allows Temporal to detect dead workers faster than
# waiting for the full start_to_close_timeout to expire. Activities must
# send heartbeats within this interval or Temporal will consider them failed
# and schedule a retry on another worker.
COMPUTE_HEARTBEAT_TIMEOUT = timedelta(seconds=60)  # 1 minute - compute is mostly CPU-bound
LLM_HEARTBEAT_TIMEOUT = timedelta(seconds=120)  # 2 minutes - agent runs can have long pauses between LLM calls
EMIT_HEARTBEAT_TIMEOUT = timedelta(seconds=30)  # 30 seconds - ClickHouse writes are fast

# Schedule-to-close timeouts - caps total time including all retry attempts,
# backoff intervals, and queue time. Prevents runaway retries from blocking
# the workflow indefinitely.
COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=300)  # 5 min (2 attempts * 120s + backoff)
LLM_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=900)  # 15 min (2 attempts * 600s + backoff, capped)
EMIT_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=150)  # 2.5 min (2 attempts * 60s + backoff)

# Compute activity - CPU bound, quick retries
COMPUTE_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# LLM activity - external dependency, longer intervals between retries
LLM_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# Event emission - database write, quick retries
EMIT_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# Coordinator retry policies
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

# Event properties
EVENT_NAME = "$ai_trace_clusters"
EVENT_NAME_GENERATION = "$ai_generation_clusters"  # For generation-level clustering

# Document type for LLM trace summaries (clustering uses detailed mode only)
# New format includes mode suffix
LLMA_TRACE_DOCUMENT_TYPE = "llm-trace-summary-detailed"
LLMA_GENERATION_DOCUMENT_TYPE = "llm-generation-summary-detailed"  # For generation-level clustering
# Legacy format (before mode suffix was added) - used with rendering filter
LLMA_TRACE_DOCUMENT_TYPE_LEGACY = "llm-trace-summary"
# Legacy rendering value for detailed summaries
LLMA_TRACE_RENDERING_LEGACY = "llma_trace_detailed"

# Product for LLM trace summaries (matches sorting key in posthog_document_embeddings)
LLMA_TRACE_PRODUCT = "llm-analytics"

# Cluster labeling agent configuration
LABELING_AGENT_MODEL = "gpt-5.2"  # OpenAI GPT-5.2 for reasoning
LABELING_AGENT_MAX_ITERATIONS = 50  # Max agent iterations before forced finalization
LABELING_AGENT_RECURSION_LIMIT = 150  # LangGraph recursion limit (> 2 * max_iterations)
LABELING_AGENT_TIMEOUT = 600.0  # 10 minutes for full agent run

# HDBSCAN clustering parameters
DEFAULT_MIN_CLUSTER_SIZE_FRACTION = 0.01  # 1% of samples as minimum cluster size
MIN_CLUSTER_SIZE_FRACTION_MIN = 0.01  # Minimum allowed value for min_cluster_size_fraction
MIN_CLUSTER_SIZE_FRACTION_MAX = 0.5  # Maximum allowed value for min_cluster_size_fraction
DEFAULT_HDBSCAN_MIN_SAMPLES = 5  # Minimum samples in neighborhood for core points
DEFAULT_UMAP_N_COMPONENTS = 100  # Dimensionality for clustering (not visualization)
DEFAULT_UMAP_N_NEIGHBORS = 15  # UMAP neighborhood size
DEFAULT_UMAP_MIN_DIST = 0.0  # Tighter packing for clustering (vs 0.1 for visualization)

# Noise cluster ID (HDBSCAN convention)
NOISE_CLUSTER_ID = -1
