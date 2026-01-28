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
# Temporal configuration
WORKFLOW_NAME = "llma-trace-clustering"
COORDINATOR_WORKFLOW_NAME = "llma-trace-clustering-coordinator"
COORDINATOR_SCHEDULE_ID = "llma-trace-clustering-coordinator-schedule"
CHILD_WORKFLOW_ID_PREFIX = "llma-trace-clustering-team"

# Generation-level schedule configuration (reuses same coordinator workflow with different inputs)
GENERATION_COORDINATOR_SCHEDULE_ID = "llma-generation-clustering-coordinator-schedule"

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

# Team allowlist (empty list = no teams processed)
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
