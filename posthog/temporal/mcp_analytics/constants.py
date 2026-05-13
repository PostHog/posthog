"""Configuration constants for MCP analytics workflows."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Document layout in posthog_document_embeddings
MCP_ANALYTICS_PRODUCT = "mcp-analytics"
INTENT_DOCUMENT_TYPE = "intent"
AI_SPAN_REASONING_DOCUMENT_TYPE = "ai-span-reasoning"
EMBEDDING_RENDERING = "mcp-analytics-v1"

# The smaller (1536-dim) model is plenty for short intent strings and span snippets,
# and lets the embedding worker keep pace with daily ingestion at reasonable cost.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small-1536"

# Window sizing
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_INTENT_SAMPLES = 2000
DEFAULT_MAX_SPAN_SAMPLES = 2000

# How much of a $ai_span reasoning string we keep for embedding — keeps payloads
# small and avoids burning OpenAI tokens on long traces. Intents are already short
# (`$mcp_intent` is one sentence) so they aren't truncated.
MAX_SPAN_REASONING_CHARS = 2000

# Minimum samples we need before clustering is meaningful
MIN_INTENTS_FOR_CLUSTERING = 20

# Output event name (mirrors $ai_trace_clusters from LLM analytics trace clustering)
EVENT_NAME_INTENT_CLUSTERS = "$mcp_intent_clusters"

# Temporal workflow naming
EMBEDDING_EMIT_WORKFLOW_NAME = "mcp-analytics-embedding-emit"
INTENT_CLUSTERING_WORKFLOW_NAME = "mcp-analytics-intent-clustering"
EMBEDDING_EMIT_SCHEDULE_ID = "mcp-analytics-embedding-emit-schedule"
INTENT_CLUSTERING_SCHEDULE_ID = "mcp-analytics-intent-clustering-schedule"

# Cluster ID convention from HDBSCAN
NOISE_CLUSTER_ID = -1

# Activity / workflow timing
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
EMBEDDING_ACTIVITY_TIMEOUT = timedelta(seconds=120)
COMPUTE_ACTIVITY_TIMEOUT = timedelta(seconds=180)
LABEL_ACTIVITY_TIMEOUT = timedelta(seconds=300)
EMIT_ACTIVITY_TIMEOUT = timedelta(seconds=60)

DEFAULT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# LLM labeling — best-effort, single attempt is fine
LABEL_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

# HDBSCAN
DEFAULT_MIN_CLUSTER_SIZE_FRACTION = 0.05
DEFAULT_HDBSCAN_MIN_SAMPLES = 3

# UMAP for clustering (pre-HDBSCAN)
DEFAULT_UMAP_N_COMPONENTS = 50
