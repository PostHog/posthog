"""Evaluation-level clustering for LLM Analytics.

Two-stage pipeline:
  Stage A (hourly): sample $ai_evaluation events per ClusteringJob, compose a short
  text representation, and enqueue embeddings via the shared document_embeddings Kafka topic.

  Stage B (daily): per ClusteringJob, fetch accumulated embeddings, cluster (HDBSCAN),
  label, compute operational + evaluation-specific aggregates, and emit $ai_evaluation_clusters events.
"""

from posthog.temporal.llm_analytics.evaluation_clustering.coordinator import (
    LLMAEvaluationClusteringCoordinatorWorkflow,
    LLMAEvaluationSamplerCoordinatorWorkflow,
)
from posthog.temporal.llm_analytics.evaluation_clustering.sampling import sample_and_embed_for_job_activity
from posthog.temporal.llm_analytics.evaluation_clustering.workflow import (
    LLMAEvaluationClusteringWorkflow,
    LLMAEvaluationSamplerWorkflow,
)

__all__ = [
    # Workflows
    "LLMAEvaluationSamplerCoordinatorWorkflow",
    "LLMAEvaluationSamplerWorkflow",
    "LLMAEvaluationClusteringCoordinatorWorkflow",
    "LLMAEvaluationClusteringWorkflow",
    # Activities
    "sample_and_embed_for_job_activity",
]
