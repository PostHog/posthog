"""Configuration constants for trace clustering workflow."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Clustering parameters
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_SAMPLES = 1000
DEFAULT_MIN_K = 2
DEFAULT_MAX_K = 10

# Minimum traces required for clustering
MIN_TRACES_FOR_CLUSTERING = 20

# Coordinator concurrency settings
DEFAULT_MAX_CONCURRENT_TEAMS = 3  # Max teams to process in parallel

# Workflow timeouts
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)

# Activity timeouts (per activity type)
COMPUTE_ACTIVITY_TIMEOUT = timedelta(seconds=120)  # Fetch + k-means + distances
LLM_ACTIVITY_TIMEOUT = timedelta(seconds=300)  # LLM API call (5 minutes)
EMIT_ACTIVITY_TIMEOUT = timedelta(seconds=60)  # ClickHouse write

# Compute activity - CPU bound, quick retries
COMPUTE_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

# LLM activity - external dependency, longer intervals between retries
LLM_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

# Event emission - database write, quick retries
EMIT_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

# Coordinator retry policies
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

# Event properties
EVENT_NAME = "$ai_trace_clusters"

# Rendering type for clustering (only use detailed embeddings)
LLMA_TRACE_DETAILED_RENDERING = "llma_trace_detailed"

# Document type for LLM trace summaries
LLMA_TRACE_DOCUMENT_TYPE = "llm-trace-summary"

# Product for LLM trace summaries (matches sorting key in posthog_document_embeddings)
LLMA_TRACE_PRODUCT = "llm-analytics"

# Team allowlist (empty list = no teams processed)
ALLOWED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    112495,  # Dogfooding project
]

# Cluster labeling configuration
DEFAULT_TRACES_PER_CLUSTER_FOR_LABELING = 7  # Number of representative traces to use for LLM labeling
LABELING_LLM_MODEL = "gpt-5.1"
LABELING_LLM_TIMEOUT = 240.0
